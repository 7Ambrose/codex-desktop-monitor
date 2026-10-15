import hashlib
import json
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .reviewer import run_review
from .notifier import notify


def redacted(value):
    text = json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", text)
    text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~-]{12,}", r"\1[REDACTED]", text)
    text = re.sub(r'(?i)("(?:access_token|refresh_token|api_key|password)"\s*:\s*")[^"\\]*(?:\\.[^"\\]*)*"', r'\1[REDACTED]"', text)
    return json.loads(text)


def within(path, root):
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


class Engine:
    def __init__(self, store, settings, local_dir, review_fn=run_review):
        self.store, self.settings, self.local_dir = store, settings, Path(local_dir)
        self.review_fn = review_fn
        self.review_queue = queue.Queue(maxsize=50)
        self.queued = set()
        self.lock = threading.RLock()
        self.last_hook_at = max((task['updated'] for task in store.tasks()), default=0)
        self.started = time.time()
        self.shutdown = threading.Event()
        self.service_error = None

    def start(self):
        threading.Thread(target=self._worker, daemon=True, name="quality-review").start()
        threading.Thread(target=self._health_worker, daemon=True, name="local-alerts").start()

    def notice(self, task, kind, message, suffix=''):
        key = f"{task['id']}:{task['turn_id'] or task['started']}:{kind}:{suffix}"
        with self.store.transaction() as db:
            added = db.execute('INSERT OR IGNORE INTO notices(id,task_id,turn_id,kind,at,message) VALUES(?,?,?,?,?,?)',
                               (key, task['id'], task['turn_id'], kind, time.time(), message)).rowcount
        if added:
            notify(task['title'][:45] + '：' + message)
        return bool(added)

    def notices(self, limit=50):
        with self.store.lock:
            return [dict(row) for row in self.store.db.execute('SELECT notices.*,tasks.title AS task_title FROM notices LEFT JOIN tasks ON tasks.id=notices.task_id ORDER BY notices.at DESC LIMIT ?', (limit,))]

    def acknowledge(self, ident):
        with self.store.transaction() as db:
            db.execute('UPDATE notices SET acknowledged=1 WHERE id=?', (ident,))

    @staticmethod
    def failed(response):
        if not isinstance(response, dict):
            return False
        for key in ('exit_code', 'exitCode'):
            if key in response and response[key] not in (0, None, '0'):
                return True
        if response.get('isError') is True:
            return True
        return any(Engine.failed(response[key]) for key in ('result', 'structuredContent') if isinstance(response.get(key), dict))

    def check_health(self, now=None):
        now = time.time() if now is None else now
        threshold = self.settings.get('stalled_notice_seconds', 600)
        for task in self.store.tasks():
            if task['state'] == 'running' and now - task['updated'] >= threshold:
                self.notice(task, 'quiet', f"疑似停滞：至少 {int(threshold/60)} 分钟没有新事件。可能仍在推理或执行长命令，请打开聊天确认。", str(int(task['updated'])))

    def _health_worker(self):
        while not self.shutdown.wait(10):
            try:
                self.check_health()
            except Exception:
                self.service_error = '本地提醒检查失败，请查看后台状态'

    def accept(self, event):
        if not isinstance(event, dict):
            raise ValueError("事件必须为对象")
        sid = event.get("session_id", "")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
            raise ValueError("无效任务 ID")
        if sid in self.settings.get("excluded_thread_ids", []):
            return {"ignored": True}
        cwd = event.get("cwd", "")
        roots = self.settings.get("enabled_roots", [])
        if not cwd or not any(within(cwd, root) for root in roots):
            return {"ignored": True}
        if within(cwd, self.local_dir) or os.environ.get("CODEX_MONITOR_REVIEWER") == "1":
            return {"ignored": True}
        event = redacted(event)
        kind = event.get("hook_event_name", "")
        if kind not in {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "Interrupt", "PreCompact", "PostCompact", "TaskFailed"}:
            raise ValueError("不支持的事件")
        turn = str(event.get("turn_id") or "")
        now = time.time()
        with self.lock, self.store.transaction() as db:
            task = self.store.task(sid)
            if not task:
                db.execute("INSERT INTO tasks(id,title,cwd,model,turn_id,state,started,updated) VALUES(?,?,?,?,?,?,?,?)",
                           (sid, "新任务", cwd, event.get("model", ""), turn, "observing", now, now))
                task = self.store.task(sid)
            # A late completion from another turn must not overwrite the currently active turn.
            stale = bool(turn and task["turn_id"] and turn != task["turn_id"] and kind not in {"UserPromptSubmit", "SessionStart"})
            db.execute("INSERT INTO events(task_id,turn_id,at,kind,payload) VALUES(?,?,?,?,?)",
                       (sid, turn, now, kind, json.dumps(event, ensure_ascii=False)))
            if stale:
                return {"stale": True}
            self.last_hook_at = now
            db.execute("UPDATE tasks SET updated=?,last_event=?,cwd=?,model=? WHERE id=?",
                       (now, kind, cwd, event.get("model", task["model"]), sid))
            if kind == "UserPromptSubmit":
                prompt = str(event.get("prompt", ""))[:24000]
                # Keep steering history with a hard bound; original user text is never replaced by model interpretation.
                history = (task["prompt"] + "\n\n[用户后续消息]\n" + prompt)[-48000:] if task["prompt"] else prompt
                db.execute("UPDATE tasks SET title=?,prompt=?,turn_id=?,revision=revision+1,state=?,started=?,pause_confirmed=0,review_count=0,last_message='',review=NULL WHERE id=?",
                           (prompt[:64] or "新任务", history, turn, 'pause_requested' if task['pause_reason'] else 'running', now, sid))
            elif kind == "PreToolUse" and task["state"] not in {"pause_requested", "waiting_user"}:
                db.execute("UPDATE tasks SET state='running',turn_id=CASE WHEN ? != '' THEN ? ELSE turn_id END WHERE id=?", (turn, turn, sid))
            elif kind == "Stop":
                db.execute("UPDATE tasks SET state=CASE WHEN pause_reason IS NULL THEN 'finished' ELSE 'needs_attention' END,last_message=? WHERE id=?",
                           (str(event.get("last_assistant_message") or "")[:24000], sid))
            elif kind == "Interrupt":
                db.execute("UPDATE tasks SET state='interrupted',pause_confirmed=1 WHERE id=?", (sid,))
            elif kind == 'TaskFailed':
                db.execute("UPDATE tasks SET state='error',last_message=? WHERE id=?",(str(event.get('last_assistant_message',''))[:24000],sid))
            # Revisions identify semantic snapshots; new tool activity invalidates an in-flight judgment.
            if kind in {"PreToolUse", "PostToolUse", "Stop"}:
                db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (sid,))
        if kind == "PostToolUse":
            self._repeated_failure(sid)
        elif kind == "Stop":
            if self.settings.get('notify_completed', True):
                self.notice(self.store.task(sid), 'finished', '本轮执行已结束，尚不代表交付质量已核验。')
            mode = self.settings.get('review_mode', 'economy')
            if mode == 'comprehensive':
                self.request_review(sid, "交付节点")
            elif mode == 'balanced' and self._artifacts(self.store.task(sid)):
                self.request_review(sid, "文件交付节点")
        elif kind == 'Interrupt' and self.settings.get('notify_interrupted', True):
            self.notice(self.store.task(sid), 'interrupted', '任务已中断，可打开原聊天查看原因或手动继续。')
        elif kind == 'TaskFailed':
            self.notice(self.store.task(sid),'managed_error','任务执行失败，请查看面板错误。')
        return self.gate(sid)

    def _repeated_failure(self, sid):
        # Only consecutive explicit failures with exactly the same input and response qualify.
        events = [e for e in self.store.events(sid, 30) if e["kind"] in {"PostToolUse", "UserPromptSubmit"}]
        same = []
        failures = 0
        for item in reversed(events):
            if item['kind'] == 'UserPromptSubmit' or not self.failed(item['payload'].get('tool_response')):
                break
            failures += 1
        if failures >= self.settings['repeat_failure_count']:
            self.notice(self.store.task(sid), 'failures', '工具已连续报错，请查看最近错误；尚未自动停止任务。')
        for item in reversed(events):
            if item["kind"] == "UserPromptSubmit":
                break
            event = item["payload"]
            response = event.get("tool_response", {})
            if not self.failed(response):
                break
            fingerprint = hashlib.sha256(json.dumps([event.get("tool_name"), event.get("tool_input"), response], sort_keys=True).encode()).hexdigest()
            if same and fingerprint != same[-1]:
                break
            same.append(fingerprint)
        if len(same) >= self.settings["repeat_failure_count"]:
            self.request_review(sid, "同一操作连续失败")

    def gate(self, sid):
        task = self.store.task(sid)
        paused = bool(task and task["pause_reason"] and task["state"] in {"pause_requested", "waiting_user", "needs_attention"})
        return {"paused": paused, "reason": task["pause_reason"] if paused else None,
                "checkpoint_declined": bool(task and task['control'] == 'denied'),
                "turn_id": task["turn_id"] if task else None, "state": task["state"] if task else "unknown"}

    def request_pause(self, sid, reason, expected_turn=None):
        with self.lock, self.store.transaction() as db:
            task = self.store.task(sid)
            if not task:
                raise ValueError("任务不存在")
            if expected_turn is not None and expected_turn != task["turn_id"]:
                raise ValueError("任务轮次已变化，请刷新")
            if task['pause_reason'] == reason:
                return self.gate(sid)
            active = task["state"] in {"running", "observing", "pause_requested", "waiting_user"}
            state = "pause_requested" if active else "needs_attention"
            db.execute("UPDATE tasks SET state=?,pause_reason=?,pause_confirmed=0 WHERE id=?", (state, reason, sid))
            db.execute("INSERT INTO decisions(task_id,turn_id,at,action,reason) VALUES(?,?,?,?,?)", (sid, task["turn_id"], time.time(), "pause_requested", reason))
        notify(reason)
        return self.gate(sid)

    def checkpoint_waiting(self, sid, turn):
        with self.lock, self.store.transaction() as db:
            db.execute("UPDATE tasks SET state='waiting_user',pause_confirmed=0 WHERE id=? AND turn_id=? AND state='pause_requested'", (sid, turn))

    def checkpoint_declined(self, sid, turn):
        with self.lock, self.store.transaction() as db:
            db.execute("UPDATE tasks SET state='pause_requested',control='denied' WHERE id=? AND turn_id=? AND state='waiting_user'", (sid, turn))

    def release(self, sid, expected_turn):
        with self.lock, self.store.transaction() as db:
            task = self.store.task(sid)
            if not task or task["turn_id"] != expected_turn:
                raise ValueError("任务轮次已变化，请刷新")
            state = "running" if task["state"] in {"waiting_user", "pause_requested"} else "finished"
            db.execute("UPDATE tasks SET state=?,pause_reason=NULL,pause_confirmed=0,control='checkpoint',revision=revision+1 WHERE id=?", (state, sid))
            db.execute("INSERT INTO decisions(task_id,turn_id,at,action,reason) VALUES(?,?,?,?,?)", (sid, expected_turn, time.time(), "user_release", "用户允许继续"))

    def request_review(self, sid, reason, manual=False):
        task = self.store.task(sid)
        if not task:
            raise ValueError("任务不存在")
        if not self.settings.get("review_enabled"):
            return {"queued": False, "reason": "复核已关闭"}
        day_start = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.store.lock:
            used = self.store.db.execute("SELECT count(*) FROM decisions WHERE action='review_started' AND at>=?", (day_start,)).fetchone()[0]
        if used + self.review_queue.qsize() >= self.settings.get('review_daily_limit', 10):
            return {"queued": False, "reason": "已达到今天的复核次数上限"}
        if task["review_count"] >= self.settings["review_limit_per_turn"]:
            return {"queued": False, "reason": "已达到每轮复核上限"}
        if not manual and time.time() - task["reviewed_at"] < self.settings["review_cooldown_seconds"]:
            return {"queued": False, "reason": "复核冷却中"}
        with self.lock:
            if sid in self.queued:
                return {"queued": False, "reason": "已有复核排队"}
            try:
                self.review_queue.put_nowait((sid, reason))
            except queue.Full:
                return {"queued": False, "reason": "复核队列已满"}
            self.queued.add(sid)
        return {"queued": True}

    def snapshot(self, sid):
        task = self.store.task(sid)
        return {"task_id": sid, "turn_id": task["turn_id"], "revision": task["revision"],
                "user_requirements": task["prompt"], "cwd": task["cwd"], "state": task["state"],
                "last_message": task["last_message"], "events": self.store.events(sid),
                "artifact_checks": self._artifacts(task),
                "limitations": ["未读取的产物不算已验证", "未渲染文档不能评判版式", "工具输出可能不完整"]}

    def _artifacts(self, task):
        text = task['prompt'] + '\n' + task['last_message']
        candidates = re.findall(r'[A-Za-z]:[\\/][^\s<>\"\)\]\u3002\uFF0C]+', text)
        checks = []
        for raw in dict.fromkeys(candidates):
            path = Path(raw.rstrip('.,;:'))
            if not within(path, task['cwd']) or any(part.lower() in {'.git', '.codex', '.ssh', '.local'} for part in path.parts):
                continue
            if any(word in path.name.lower() for word in ('auth', 'token', 'secret', 'credential', '.env', 'password')):
                continue
            item = {'path': str(path), 'exists': path.exists()}
            if path.is_file():
                stat = path.stat()
                item.update(size=stat.st_size, modified_at=stat.st_mtime)
                if stat.st_size <= 65536 and path.suffix.lower() in {'.txt', '.md', '.csv', '.json', '.py', '.js', '.html', '.css'}:
                    try:
                        item['excerpt'] = redacted(path.read_text(encoding='utf-8')[:3000])
                    except (UnicodeError, OSError):
                        item['content_status'] = '无法读取文本'
                else:
                    item['content_status'] = '未核验内容或版式'
            checks.append(item)
            if len(checks) == 8:
                break
        return checks

    def apply_review(self, snapshot, result, usage):
        sid = snapshot["task_id"]
        with self.lock, self.store.transaction() as db:
            task = self.store.task(sid)
            stale = not task or task["turn_id"] != snapshot["turn_id"] or task["revision"] != snapshot["revision"]
            db.execute("INSERT INTO reviews(task_id,turn_id,revision,at,verdict,result,usage,stale) VALUES(?,?,?,?,?,?,?,?)",
                       (sid, snapshot["turn_id"], snapshot["revision"], time.time(), result["verdict"], json.dumps(result, ensure_ascii=False), json.dumps(usage), int(stale)))
            if stale:
                return False
            # A quoted requirement has to exist in actual user text; model assertions alone cannot trigger automatic control.
            quote_valid = result["requirement_quote"] and result["requirement_quote"] in snapshot["user_requirements"]
            db.execute("UPDATE tasks SET review=? WHERE id=?", (json.dumps(result, ensure_ascii=False), sid))
            if result["should_pause"] and quote_valid and result["evidence"] and self.settings.get("auto_pause"):
                self.request_pause(sid, result["summary"], snapshot["turn_id"])
            return True

    def _worker(self):
        while not self.shutdown.is_set():
            try:
                sid, reason = self.review_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                with self.store.transaction() as db:
                    db.execute("UPDATE tasks SET reviewed_at=?,review_count=review_count+1 WHERE id=?", (time.time(), sid))
                    db.execute("INSERT INTO decisions(task_id,turn_id,at,action,reason) VALUES(?,?,?,?,?)", (sid, self.store.task(sid)['turn_id'], time.time(), 'review_started', reason))
                snapshot = self.snapshot(sid)
                snapshot["trigger"] = reason
                result, usage = self.review_fn(snapshot, self.settings, self.local_dir)
                self.apply_review(snapshot, result, usage)
            except Exception as exc:
                with self.store.transaction() as db:
                    db.execute("UPDATE tasks SET review=? WHERE id=?", (json.dumps({"verdict": "unavailable", "summary": str(exc)[:300]}, ensure_ascii=False), sid))
            finally:
                with self.lock:
                    self.queued.discard(sid)
                self.review_queue.task_done()
