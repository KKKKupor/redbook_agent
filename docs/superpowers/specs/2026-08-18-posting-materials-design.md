# 发帖备稿链路设计 — 封面截图 + 素材推送 + 定时发布对齐

**日期**: 2026-08-18
**状态**: 已获用户批准
**范围**: 小红书笔记/商品发布的"备稿"环节 —— 系统产出文案+三张图+建议发布时间,人工贴稿发布

## 1. 背景与目标

上架一个商品需要:发一篇笔记(帖子)+ 橱窗挂商品。笔记发布没有官方 API,自动发帖有封号风险,因此采用"系统备稿 + 人工贴稿 + 官方定时发布"路线(路线C,用户已确认)。

**目标**:
1. 系统自动产出:种草文案(已有)、3 张图片(新增)、建议发布时间(已有)
2. 素材通过钉钉单独一条消息推送,人工 1 分钟内完成贴稿
3. 发布时间决策(`scheduled_publish_time`)通过小红书官方定时发布功能真实落地

**非目标(不在本设计内)**:订单回收、橱窗自动化、Playwright 自动发帖、图片加字贴纸等后期美化。

## 2. 三张图片规格

| 文件 | 用途 | 视口 | 内容 |
|---|---|---|---|
| `cover.png` | 笔记封面图 | 750×1000(3:4) | HTML 起始页(图标+标题+卖点+开始按钮) |
| `result.png` | 笔记封面图 | 750×1000(3:4) | 结果页顶部(多维雷达图+人格标签) |
| `product.png` | 商品主图(橱窗上传) | 1000×1000(1:1,即用户所称 4:4) | HTML 起始页 |

三张图均为 Playwright 截图,无 LLM 图片生成成本。

## 3. 架构与数据流

```
packager ──generated_html / packaging_text──▶ publisher
                                                │ 写 output/deploy/latest/index.html
                                                │ 调 utils/cover_shots.capture_cover_images → 3 张 png 写入 deploy 目录
                                                │ _deploy_to_vercel 部署(含图片,不重试逻辑改动)
                                                │ 返回 html_url + cover_image_url + result_image_url + product_image_url
                                                ▼
main.py run_once ──▶ 日报推送(照旧,不动格式)
                  ──▶ utils/posting_materials.build_message(result) → 钉钉「发帖素材」消息(单独一条)
人工: App 发笔记 → 贴文案 → 传 2 张封面 → 定时发布(填建议时间) → 橱窗选品传商品主图 → 关联笔记
```

**新增 state 字段**(`graph/state.py`):
- `cover_image_url: str`
- `result_image_url: str`
- `product_image_url: str`

## 4. 模块设计

### 4.1 `utils/cover_shots.py`(新文件)

单一职责:给定 HTML 文件路径,产出 3 张截图。使用 Playwright **sync API**(publisher 是同步节点;项目其余 Playwright 用法为 async,不冲突)。

```python
def capture_cover_images(html_path: Path, out_dir: Path) -> dict:
    """返回 {"cover": Path, "result": Path, "product": Path}(失败时缺键或抛异常由调用方处理)"""
```

流程:
1. 启动 Chromium(默认 headless),fresh context(无 localStorage 残留)
2. 视口 750×1000 → 打开 file:// HTML → 等 domcontentloaded → 截起始页 = `cover.png`
3. 点 `#btn-start-new` 进入答题 → 循环:点第一个 `.option-btn` → 点 `#btn-next`,直到 `#results-section` 可见(循环上限 = 题数 + 20 兜底,防死循环)
4. 等 Chart.js CDN 加载(`typeof Chart !== 'undefined'`,超时 15s)→ 再等 1.5s 让图表动画完成 → 滚动到结果区顶部 → 截视口 = `result.png`
5. 视口改为 1000×1000 → 重新加载 HTML → 截起始页 = `product.png`

依赖的模板 DOM(已确认存在):`#btn-start-new`、`.option-btn`、`#btn-next`、`#results-section`、`#radarChart`。Chart.js 走 jsdelivr CDN,国内网络偶尔慢——超时不阻塞,照常截图。

提供手工验证入口:`python -m utils.cover_shots <html文件路径>`(CLI,输出到当前目录)。

### 4.2 `utils/posting_materials.py`(新文件)

单一职责:纯函数组装钉钉 markdown 消息,不发送。便于单测。

```python
def build_message(state: dict) -> str | None:
    """输入 workflow 结果 state,输出钉钉 markdown 消息体(不含 title)。
    packaging_text 缺失时返回 None,由调用方(main.py)跳过推送。"""
```

消息模板:

```
**文案**: {packaging_text}
**建议发布时间**: {MM-DD HH:MM}(navigator 21:00±抖动)
**商品链接**: {html_url}
**操作**: App → 发笔记 → 贴文案 → 传2张封面 → 定时发布 → 橱窗传商品主图 → 关联笔记
![封面-起始页]({cover_image_url})
![封面-结果页]({result_image_url})
![商品主图]({product_image_url})
```

### 4.3 `agents/publisher/src/main.py`(修改)

`publisher_node` 在写 `index.html` 之后、部署之前:
1. 调 `capture_cover_images`,3 张 png 写入 deploy 目录(与 index.html 一起部署)
2. 部署成功后由 Vercel URL 推导图片 URL:`https://{url}/cover.png` 等(Vercel 返回的 url 无 scheme,需补 `https://`)
3. state 返回新增 3 个 URL 字段

### 4.4 `main.py`(修改)

`run_once` 在日报推送之后:
1. `msg = build_message(result)`;返回 None(如 packaging_text 缺失)则跳过素材推送
2. 标题 `小红书发帖素材 - {topic}`(含"小红书"关键词,过钉钉过滤器),`notifier.send(level="info")`,失败仅警告(与日报一致)
3. `token_reset()` 位置不变(发帖素材推送无 LLM 调用,不影响成本结算)

### 4.5 其他改动

- `graph/state.py`:新增 3 个 URL 字段
- **不改**:workflow 图结构、packager、auditor、日报格式、Vercel 部署逻辑(仅部署目录多了图片文件)

## 5. 错误处理矩阵

| 场景 | 行为 |
|---|---|
| 截图抛异常(浏览器/超时) | 主流程不中断;素材消息照发,图片行替换为"⚠️ 封面图生成失败,请自行配图" |
| 部署失败(现有 fallback 本地路径) | 素材消息注明"⚠️ 部署失败,商品链接与图片无公网 URL" |
| Chart.js CDN 15s 超时 | 直接截 result.png(图中可能无雷达图),不重试 |
| packaging_text 缺失 | 跳过素材消息,只发日报 |
| 消息发送失败 | 仅 logger.warning,不影响主流程 |

## 6. 测试策略

- `utils/posting_materials.py` 的 `build_message`:**TDD,先写测试**。覆盖:全字段齐全 / 截图失败(无图) / 部署失败 / packaging_text 缺失(返回 None 或空)四态
- `utils/cover_shots.py`:依赖浏览器+CDN+模板 DOM,不写自动测试;提供 CLI 手工验证入口(与 `tools/xhs_search.py` 的 live 部分同模式)
- 项目测试风格:pytest,现有 tests/ 目录,参照 `tests/test_xhs_search.py` 的 monkeypatch 模式

## 7. 验收标准

1. `pytest` 新测试全绿,旧测试不回归
2. 手工跑通:任一 HTML 文件 → CLI 产出 3 张图,起始页/结果页/商品图尺寸分别为 750×1000 / 750×1000 / 1000×1000
3. 一次完整 `python main.py` 运行:部署目录含 3 张 png,日报+素材消息两条钉钉推送,素材消息含 3 张图的公网 URL
4. 截图失败或部署失败时,素材消息仍到达且降级提示正确

## 8. 附带项(不随本设计实施)

- packager 的 `agents/output/` 路径 bug(`agents/packager/src/main.py:256`,3 级 parent 应为 4 级):与本链路无依赖(publisher 读 state 的 `generated_html`),按"精准修改"原则不擅自修,建议另起提交处理
- `docs/` 目录为新建,加入 git 跟踪即可(不涉及 .gitignore 变更)
