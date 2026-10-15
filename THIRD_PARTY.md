# 第三方组件

日常状态显示采用 [LH-03/codex-monitor-hud](https://github.com/LH-03/codex-monitor-hud)，MIT 许可。

- 固定版本：v3.3.0
- 源码提交：d9ac8537e1763fac470ffb55d6abdf7aa83a0f44
- Windows x64 官方压缩包 SHA256：`5d0138ad6dd7d478f3c5788ba6c0dd5a7a08bdb1275e195cd537d5320ab17368`
- 安装方式：使用官方 Release，校验 SHA256 后运行包内 `scripts/install.ps1 -DefaultLanguage zh-CN -UseBundledRuntime`。

HUD 提供状态、Token 和用量显示；本仓库提供额外的任务复核与下一次工具操作确认。HUD 的暂停按钮仅暂停 HUD 更新，不表示 Codex 任务已停止。

默认不安装 HUD 可选 MCP 插件，避免向编码任务额外暴露工具。两个组件独立运行，基础监控不调用模型。第三方源码、二进制与个人运行数据不纳入本仓库。
