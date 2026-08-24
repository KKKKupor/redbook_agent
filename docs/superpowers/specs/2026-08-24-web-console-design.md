# Web 控制台设计 — Linear 风格流式工作台

**日期**: 2026-08-24
**状态**: 已获用户批准
**范围**: 交互式 HTML 页面(像钉钉发消息给 navigator 一样),逐 agent 流式输出思考过程(Claude 式);后续由用户个人网页跳转公开使用。访问控制:每 IP 每日 1 次。

## 1. 目标

1. 单页 HTML 控制台:输入指令(如"做一个人格阴影测试,15题")→ 触发 navigator→generator→packager→publisher 四段链
2. 每个 agent 的 LLM 输出**逐 token 流式**呈现(思考过程可见),非 LLM 步骤(截图/部署)以状态事件呈现
3. 完成后展示商品链接与成本
4. 风格:garden-skills 的 **Linear recipe**(暖黑 #08090A、发丝描边、紫色 #5E6AD2 仅激活态、mono 呈现 agent 输出)

## 2. 架构

```
web_console.py(新,FastAPI + uvicorn,端口 8090)
  GET  /                → templates/web_console.html(静态单文件,Linear 风格)
  POST /api/generate    → SSE(text/event-stream)流

SSE 事件序列:
  agent_start{key,name} → token{key,text}×N → agent_done{key,summary}
  step{message}         → ...四段链... → done{url,cost} | error{message}
```

**流式机制(核心)**:`utils/stream_bus.py` 提供 contextvar 事件总线(无 emitter 时 emit 为 no-op,日常调度零影响);`llm_factory` 每个模型构造时挂 `_TokenStreamHandler(agent_key)`(on_llm_new_token → emit)并 `streaming=True`——**不改任何 agent 主体代码**。第一步 spike 验证构造期 callbacks 可行性,失败则退路为包一层调用点。

## 3. 前端(Linear recipe 关键值)

- 调色:Ground #08090A / Surface1 #16171C / Surface2 #1E1F25 / 发丝 rgba(255,255,255,0.06) / 正文 #F7F8F8 / 次文 #9CA3AF / 强调 #5E6AD2
- 字体:Inter(标题 600 紧凑字距)、等宽字体呈现 agent 流式文本(暗底 #1E1F25、字色 #A78BFA)
- 圆角 ≤12、动效 ease-out 150ms、无弹跳弹簧、无多彩渐变
- 布局:顶部品牌条 + 对话流(用户气泡 + 生成回合块)+ 底部输入;回合块 = 四张 agent 卡片(状态灯:等待灰/运行紫脉冲/完成绿/失败红 + 流式文本 + 可折叠结果 JSON + 耗时);自动滚动带"回底部"按钮;移动端响应式
- 空状态:示例指令 chips

## 4. 访问控制

- `utils/daily_limit.py`:`DailyLimit` 类,`data/rate_limit.json` 持久化 `{ip: "YYYY-MM-DD"}`,**每 IP 每日 1 次**;threading.Lock;`allow(ip, today=...)` 可注入日期便于测试
- IP 获取:`X-Forwarded-For` 首个(兼容 ngrok/反代),否则 `request.client.host`
- 超限 → HTTP 429 JSON;生成中同 IP → 拒绝(内存运行集)

## 5. 复用与抽取

- bot_server 的 `parse_command` 抽取为 `utils/command_parser.py`(bot_server 改为 import,web_console 共用)+ 单测
- web 首版仅支持 generate 类指令,其他指令返回"暂不支持"

## 6. 测试

- stream_bus:emitter 设置/清除/no-op emit(fake emitter)
- daily_limit:首次放行/同日拒绝/跨日放行(注入日期)/文件持久化往返
- command_parser:generate 话题与题量提取/指令分型
- SSE 链:注入 fake agents 验证事件顺序与内容(不真调 LLM)
- E2E:本地起服真实生成一次,流式肉眼验收

## 7. 范围外

发布/重做等多轮指令(二期)、账号体系、HTTPS/域名(用户自备)、限流之外的防滥用。

## 8. 附带

- garden-skills/ 目录为外部参考(用户 2026-08-24 克隆),建议加 .gitignore(与 github_example/ 同类)——待用户确认
