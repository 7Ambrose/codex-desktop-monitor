# Codex 监控 v0.1.0-preview

Windows 首个预览版，适合愿意安装运行环境并反馈问题的用户。提供源码压缩包，不是免安装 EXE；尚未在全新 Windows 电脑上完成验收。

## 有哪些功能

- 简约 HUD：活跃任务数、周额度与 5 小时额度。
- 本机中文任务面板：左侧任务列表、对话记录、底部任务输入框。
- 面板内通过官方 Codex CLI 创建任务，支持中断、补充要求后继续、命令及文件修改审批。
- 对接入的任务记录进展，连续失败、十分钟无新事件及任务结束时尝试发送 Windows 通知。
- 可选独立 GPT 复核，默认省用量；普通状态轮询不调用模型。
- 桌面“Codex HUD”和“Codex 监控”快捷方式，当前用户登录启动观察进程，随 Codex 开关后台。
- 额度读取遇到短暂错误最多重试三次，不用旧数字冒充实时额度。

## 安装前准备

1. Windows 10/11 x64。
2. 安装 [Python 3.11 或更新版本](https://www.python.org/downloads/windows/)，保留 Python Launcher 或勾选加入 PATH；需要同目录的 `pythonw.exe`。
3. 安装 [Node.js 22 或更新版本](https://nodejs.org/)。不需要运行 `npm install`。
4. 安装并登录官方 Codex。监控沿用你的登录状态，不提供账号，也不包含订阅额度；必要时先运行 `codex login`。CLI 回答需要连接 OpenAI，受管任务中的命令联网权限则默认受限。
5. 安装独立 HUD：从 [Codex Monitor HUD v3.3.0](https://github.com/LH-03/codex-monitor-hud/releases/tag/v3.3.0) 下载 `CodexMonitorHUD-windows-x64.zip`，解压后在其目录运行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -DefaultLanguage zh-CN -UseBundledRuntime -SkipLaunch -SkipShortcuts
   ```

   官方 HUD 包的 SHA256：`5d0138ad6dd7d478f3c5788ba6c0dd5a7a08bdb1275e195cd537d5320ab17368`。可以使用 `Get-FileHash .\CodexMonitorHUD-windows-x64.zip -Algorithm SHA256` 核对。第三方安装器会登记 HUD 插件；不需要另外安装或启用其可选 MCP。

## 安装和使用

1. 下载本 Release 的 `codex-monitor-v0.1.0-preview-windows-source.zip`，解压到一个准备长期保留的文件夹。快捷方式会引用它，不要随后移动或删除。
2. 双击 `安装.cmd`。它会检查运行环境、备份并合并 Codex MCP/Hook 定义，建立两个桌面快捷方式和当前用户的 `CodexMonitorLifecycle` 登录任务。系统策略可能限制计划任务创建；失败时按报错处理，不能认为自启已经安装。
3. 根据 Codex 官方流程审核并信任新钩子，重启 Codex。仅看到 HUD 不代表桌面对话已接入监控。
4. 在 `settings.local.json` 的 `enabled_roots` 中设置实际工作文件夹。首次默认范围是解压目录的父文件夹，请先检查。
5. 双击“Codex HUD”打开小浮标；双击“Codex 监控”打开详细面板。面板新建的任务可以在面板中断和继续；原桌面对话仍在原窗口操作。

## 用量与数据

基础监控、额度读取和轮询不消耗模型 Token。面板执行任务、自动触发或手动请求独立复核会消耗你自己的模型额度。默认复核为 GPT-6 Luna、低思考强度，每轮最多一次、至少间隔十分钟、每天最多十次；模型是否可用取决于账号。

运行数据、随机访问令牌、备份和个人设置只保存在你的本机，不包含在发布包中。详细面板仅监听 `127.0.0.1`，不要将带令牌的面板地址转发给别人。发布包的 `SHA256SUMS.txt` 可用于校验附件。

## 已知限制

- 不会自动救活卡死对话，不自动重启、续跑或批准命令。
- 只能完整控制从本面板创建的任务。对原桌面对话的拦截依赖受信任的钩子和客户端确认能力，发生在下一次工具操作前；已经运行的命令可能继续。
- 无事件不等于确认卡死；通知会受系统勿扰设置影响。
- HUD 刷新持续失败时仍会显示 `--`；不保证额度持续可读。
- 当前电脑已验证真实任务的启动、中断和继续，以及 HUD 心跳；升级安装、首次登录自启和不同 Windows 环境仍需进一步验证。

## 卸载

在安装目录运行 `python configure.py uninstall`，移除本项目的 MCP/Hook 定义。随后在任务计划程序停止并删除 `CodexMonitorLifecycle`，删除本项目两个桌面快捷方式；旧版可能还有启动文件夹中的 `Codex Monitor Lifecycle.lnk`。HUD 是独立第三方组件，按其卸载说明单独处理。最后再删除安装目录；里面的 `.local` 保存本机日志和备份。

## 分享

仓库目前保持私有，Release 链接仅对有仓库访问权限的人可用。也可以下载本 Release 的干净源码附件，再直接发给对方。不要把正在使用的整个安装文件夹直接打包，以免夹带个人配置、日志或令牌。

第三方组件与许可见 `THIRD_PARTY.md` 和 `vendor/supervisor/LICENSE`。
