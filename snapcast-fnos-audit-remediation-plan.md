# snapcast-fnos 综合审计整改任务书

> 适用仓库：<https://github.com/jgqq0902-cmyk/snapcast-fnos>  
> 基线分支：`main`  
> 文档用途：交由其他 Coding Agent / Review Agent 直接执行整改  
> 审计范围：安全、容器权限、FNOS 部署、Snapcast 控制面、Web API、前端信息架构、播放逻辑、多房间模型、移动端交互、视觉系统、前端工程结构、状态同步、测试体系  
> 原则：**优先修复安全边界和播放逻辑，再做架构重构，最后做视觉与工程质量提升。不得只做 CSS 美化而忽略状态模型。**

---

# 1. 总体目标

将当前项目从“可信局域网内可用的 Snapcast/FNOS 管理控制台”，升级为：

> **安全边界明确、可长期运行、支持真正多房间播放、移动端体验完整、前端结构可维护的 FNOS 多房间音乐控制中心。**

目标架构：

```text
LAN
 │
 ├── 1704  Snapcast audio streaming      ← LAN 可访问
 ├── 1781  Web Control                   ← 有认证/可配置可信 LAN 模式
 ├── AirPlay / DLNA                      ← LAN 可访问
 │
 └─X─ 1780 / 1705 Snapcast control       ← 仅 localhost

                     Web Control
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Sources          Zones          Music
          │              │              │
   AirPlay/MPD/DLNA     Group         Library
                         │            Playlists
                    Snap Clients
                         │
                Volume / Latency
                         │
                  Playback Session
                         │
                  Queue / Now Playing
```

前端核心产品模型必须从“设备/队列/歌单/曲库”转向：

```text
正在播放什么 → 在哪里播放 → 接下来播放什么
```

---

# 2. 执行规则（所有 Agent 必须遵守）

1. **先读现有代码和测试再修改，不允许凭假设重写。**
2. **不得为了前端重构引入 React/Vue/Node 构建链。** 本项目继续使用 Vanilla JS + CSS + Python 后端。
3. **不得破坏现有 AirPlay、DLNA、MPD、Snapcast 基础能力。**
4. **不得把 Snapcast 1704 音频流端口限制到 localhost。** 只限制控制面 1780/1705。
5. **不得让 UI 再用字符串或 URL 猜测 source 类型。** source/capabilities 由后端明确返回。
6. **不得继续把 Group 扁平化成 Client 列表。** Group/Zone 必须成为前端一级对象。
7. **不得让 Queue 中“播放此曲”走 `play-now(clear→add→play)`。** Queue 必须使用 position/id 语义播放。
8. **不得仅通过隐藏按钮解决移动端空间问题。** 移动端要重构交互语义。
9. **不得继续增加新的全局 CSS 覆盖补丁文件。** 逐步清理 `refinements.css` 式覆盖链。
10. 每个 P0/P1 任务完成后必须补对应测试；若无法自动化测试，必须写清人工验收步骤。
11. 修改完成后，输出：
   - 变更摘要
   - 修改文件列表
   - 新增/修改测试
   - 未完成项与原因
   - 潜在兼容风险

---

# 3. 整改优先级

## P0 — 必须先完成

- SEC-01 Web 控制 API 身份认证
- SEC-02 Snapcast 原生控制面收口到 localhost
- SEC-03 长期服务降权运行
- UI-01 Group/Zone 一等对象化
- UI-02 Zone 级 Source 状态与切换
- UI-03 Queue 点击播放不得清空队列
- UI-04 移动端曲目“立即播放”交互修复

## P1 — P0 完成后实施

- OPS-01 网络配置单一真源
- SEC-04 文件读取/扫描资源限制
- OPS-02 Docker 构建可复现
- FE-01 前端模块化
- FE-02 后端显式 sourceType/capabilities
- FE-03 状态同步从粗粒度轮询升级
- UX-01 首页 Now Playing Dashboard
- UX-02 Rooms/Zone Group-first 页面
- UX-03 Music 信息架构统一
- UX-04 移动端 Mini Player / Full Player 重构
- VIS-01 Design Token / CSS 架构
- VIS-02 动态封面取色安全化

## P2 — 收尾完善

- TEST-01 HTTP / 鉴权 / Snapcast 边界测试
- TEST-02 Docker 集成 Smoke Test
- UX-05 Dialog/Toast/主题/安全区完善
- PERF-01 搜索 AbortController 与无效请求收敛
- DOC-01 README / 部署说明 / 迁移说明

---

# 4. P0 安全整改

## SEC-01：Web 控制 API 增加认证

### 当前问题

Web Control 监听 `0.0.0.0`，可直接操作播放、音量、切流、MPD、曲库路径等，但当前无认证授权边界。

### 目标

Web Control 默认具备认证能力；允许用户显式选择“可信家庭 LAN 模式”关闭认证，但默认必须安全。

### 建议涉及文件

- `control/app.py`
- `control/static/index.html`
- `control/static/app.js`
- `docker-compose.yml`
- `unified/supervisord.conf`
- README / 示例环境变量文件

### 实现要求

建议环境变量：

```text
CONTROL_AUTH_ENABLED=true
CONTROL_USERNAME=admin
CONTROL_PASSWORD=<user configured or generated>
```

推荐实现优先级：

1. 后端登录接口；
2. 成功后发放 Session Cookie；
3. Cookie 必须：`HttpOnly`、`SameSite=Strict`；
4. HTTPS 不强制时，不错误宣称 Secure Cookie；如未来 TLS 终止于本服务，再启用 Secure；
5. 所有控制型 API 必须统一经过 auth middleware / guard；
6. 静态页面可以公开，但 `/api/*` 除登录/健康检查外默认受保护；
7. 未认证返回 `401`，不要返回模糊 `500`；
8. 登录失败必须有简单节流，避免无限高速爆破；
9. 不把密码明文写入仓库。

### 验收标准

- 未登录访问 `/api/state` → 401
- 未登录 POST 播放/音量/切流 → 401
- 错误密码 → 401
- 正确登录 → 获得 Session 并可访问 API
- `CONTROL_AUTH_ENABLED=false` 时保留原 LAN 直连能力
- Session 失效后必须重新登录

---

## SEC-02：Snapcast 1780/1705 控制面仅监听 localhost

### 当前问题

即使 Web Control 加认证，只要 Snapcast HTTP/JSON-RPC 或 TCP control 暴露在 LAN，仍可绕过 Web 控制台认证直接修改组、音量、音源。

### 涉及文件

- `snapserver.conf`
- 可能涉及 `unified/supervisord.conf`
- Docker/FNOS 网络说明

### 修改要求

明确配置：

```ini
[http]
enabled = true
bind_to_address = 127.0.0.1
port = 1780

[tcp-control]
enabled = true
bind_to_address = 127.0.0.1
port = 1705
```

保留：

```text
1704 Snapcast audio streaming 对 LAN 开放
```

Web Control 内部继续使用：

```text
http://127.0.0.1:1780/jsonrpc
```

### 验收标准

- 容器内 `127.0.0.1:1780` 可访问
- LAN 访问 `<container-ip>:1780` 失败
- LAN 访问 `<container-ip>:1705` 失败
- LAN Snapclient 仍能通过 1704 正常播放
- Web Control 切换 Zone 音源仍正常

---

## SEC-03：Web Control / MPD 等长期服务降权

### 当前问题

Supervisor 本身以 root 启动；已有部分服务指定 `user=snapcast`，但 Control/MPD 存在继承 root 的情况，MPD 还使用过宽 `umask=0000`。

### 涉及文件

- `unified/supervisord.conf`
- `unified/entrypoint.sh` 或等价启动脚本
- Dockerfile / volume 权限初始化

### 修改要求

长期网络服务尽量统一：

```ini
user=snapcast
```

重点：

- `control`
- `mpd`

并将：

```text
umask=0000
```

收紧为合理权限，例如：

```text
umask=0022
```

如写目录需要写权限：

- 由 root entrypoint 启动阶段创建目录；
- `chown snapcast:snapcast`；
- 然后长期进程降权。

不得通过给整个文件系统 `chmod 777` 解决权限问题。

### 验收标准

容器内检查：

```text
snapserver → snapcast
shairport → snapcast
upmpdcli → snapcast
mpd → snapcast
control → snapcast
```

不得因降权导致：

- 播放失败
- 数据库无法更新
- 歌单无法保存
- 封面/歌词无法读取

---

# 5. P0 多房间与播放逻辑整改

## UI-01：Group/Zone 必须成为前端一级对象

### 当前问题

后端返回 Snapcast `groups → clients`，但前端渲染时把 Group 扁平化为单个 Client 卡片，导致多房间模型被削弱。

### 目标状态

前端采用：

```text
Zone(Group)
 ├── id
 ├── name
 ├── stream/source
 ├── volume aggregate / group controls
 └── clients[]
      ├── id
      ├── name
      ├── volume
      ├── mute
      └── latency
```

### 涉及文件

- `control/app.py`
- `control/static/app.js`
- `control/static/index.html`
- CSS 文件

### UI 要求

Group/Zone 是主卡片：

```text
客厅
────────────────────
Local Music · 正在播放
一直很安静 · 阿桑

Group Volume
设备：
  客厅音箱 L
  客厅音箱 R

音源：Local / AirPlay / DLNA
高级设置：Client latency / per-client volume
```

Client 不再作为一级主卡片。

### 验收标准

至少模拟两个 Group：

```text
客厅 → Local
卧室 → AirPlay
```

页面能同时正确表达二者，且不会把它们误显示成全局单一 source。

---

## UI-02：Source 状态与切换必须按 Zone/Group

### 当前问题

前端点击音源倾向走 `/api/snapcast/all-stream`，形成“所有组统一切流”的全局语义。

### 修改要求

默认切换行为：

```text
selectedZone → Group.SetStream
```

使用单组接口：

```text
/api/snapcast/stream
```

“全部房间切换到某音源”可以保留，但必须作为明确的高级/批量动作，不得是默认行为。

### 验收标准

- 客厅切 AirPlay，不影响卧室 Local
- 卧室切 DLNA，不影响客厅
- 可明确执行“全部房间统一为 Local”，但需要单独按钮/确认语义

---

## UI-03：Queue 点击播放不得清空整个队列

### 当前问题

Queue / Playlist / Library 共用 TrackRow 操作语义。当前“立即播放”调用 `play-now`，而后端 `play-now` 会 `clear → add → play`。

在 Queue 中点击某曲会把当前队列清空。

### 修改要求

拆分“视觉组件”和“操作策略”。

```text
TrackRow UI
   ├── QueuePolicy
   ├── LibraryPolicy
   └── PlaylistPolicy
```

Queue：

```text
播放当前队列中的第 N 首 → play-position / playid
删除 → remove
移动 → reorder（若已有/新增）
```

Library：

```text
立即播放 → play-now
下一首 → add-next
加入队列 → enqueue
```

Playlist：

```text
从这里开始播放 / 加入队列 / 下一首
```

### 验收标准

给 Queue 放入 A/B/C：

- 点击 B 播放 → 队列仍为 A/B/C
- 当前播放位置切到 B
- A/C 不被删除

---

## UI-04：移动端必须保留“立即播放”主路径

### 当前问题

现有移动端通过 CSS 隐藏大部分 row action；普通曲目可能只剩“下一首”，但整行又不能点击播放。

### 修改要求

移动端 TrackRow：

```text
[封面] 歌名
       歌手 · 专辑                 ⋯
```

交互：

- 点击整行 → 主动作（Library/Playlist 下为立即播放或进入明确播放策略）
- `⋯` → Bottom Sheet / Dialog：
  - 下一首播放
  - 加入队列
  - 加入歌单
  - 查看专辑
  - 查看歌手
- Queue 中点击整行 → 播放当前位置，不清队列

触摸目标建议 ≥ 44px。

### 验收标准

手机宽度 360px/390px 下：

- 用户最多一次点击即可播放曲目
- 不需要横向滚动
- 不出现 3~5 个挤在一起的小图标按钮

---

# 6. P1 部署与资源安全

## OPS-01：网络配置单一真源

### 当前问题

容器 IP/网段配置在 Compose 中，upmpdcli 等配置又可能写死固定 IP。用户改 Compose 后可能导致 DLNA 状态不一致。

### 目标

IP/网络信息只有一个配置源。

### 推荐方案

```yaml
environment:
  GATEWAY_IP: 192.168.2.125
```

启动时模板生成：

```text
upmpdcli.conf
other IP-dependent config
```

更优方案：若运行环境稳定，可自动探测容器实际 IPv4，并允许环境变量覆盖。

### 验收标准

把容器 IP 改为另一个合法地址，只修改一处即可正常启动 AirPlay/DLNA/Web/Snapcast。

---

## SEC-04：限制目录扫描与文件读取资源消耗

### 当前问题

- Playlist 搜索可能对整个 `/media` 做 `rglob('*')`
- 封面/歌词存在 `read_bytes()` 无大小上限

### 修改要求

1. Playlist index 增加缓存：
   - TTL 30~60 秒，或
   - 显式 refresh
2. 尽量只扫描 playlist 目录；若无法保证，至少缓存全量扫描结果。
3. 文件大小上限：
   - 封面：建议 20MB
   - 歌词：建议 2~5MB
4. 超限返回明确错误，不得让 Python 一次加载超大文件。

### 验收标准

- 30 万文件目录重复请求不会每次都全盘扫描
- 100MB `folder.jpg` 不会整块读入内存
- 超大歌词文件被拒绝

---

## OPS-02：Docker 构建可复现

### 当前问题

基础镜像可能使用 `latest`，依赖又来自 Alpine edge，未来 rebuild 可能得到不同版本。

### 修改要求

- 基础镜像固定版本；正式 release 建议固定 digest
- 记录 MPD/upmpdcli/关键 Python 依赖版本
- 构建后输出版本信息
- README 写明升级策略

### 验收标准

相同 commit 在不同时间构建，不因 `latest` 漂移导致大版本变化。

---

# 7. P1 前端状态模型重构

## FE-01：拆分单体 `app.js`

### 目标结构建议

```text
control/static/js/
  api.js
  store.js
  events.js

  domains/
    playback.js
    zones.js
    library.js
    playlists.js

  views/
    home.js
    rooms.js
    music.js
    queue.js
    now-playing.js

  components/
    track-row.js
    room-card.js
    volume.js
    dialog.js
    toast.js

  app.js
```

### 状态模型建议

```text
state
 ├ system
 │   ├ health
 │   └ connection
 │
 ├ sources
 │   ├ mpd
 │   ├ airplay
 │   └ dlna
 │
 ├ zones[]
 │   ├ id
 │   ├ streamId
 │   ├ sourceType
 │   └ clients[]
 │
 ├ selectedZoneId
 ├ playback
 ├ queue
 └ library
```

### 验收标准

- 不再有单个超大文件同时包含 API、Store、Snapcast、Library、Dialog、DOM 事件全部逻辑
- 页面切换逻辑独立
- TrackRow 视觉与行为策略解耦

---

## FE-02：后端返回显式 `sourceType` 与 `capabilities`

### 当前问题

前端通过字符串/URL/名称推断 AirPlay/Local/DLNA，属于脆弱逻辑。

### 后端建议返回

```json
{
  "sourceType": "airplay",
  "capabilities": {
    "playPause": true,
    "previous": true,
    "next": true,
    "seek": false,
    "queue": false
  }
}
```

MPD/Local 示例：

```json
{
  "sourceType": "mpd",
  "capabilities": {
    "playPause": true,
    "previous": true,
    "next": true,
    "seek": true,
    "queue": true
  }
}
```

### 验收标准

前端不得再通过：

- URL 是否 `http`
- 名称是否匹配 `/airplay/i`
- stream id 文本规则

来决定功能按钮。

---

## FE-03：状态同步从 2 秒全量轮询升级

### 当前问题

高频 `GET /api/state` + 操作后额外 refresh，状态同步粗粒度。

### 推荐实现

优先 SSE：

```text
GET /api/events
```

事件：

```text
playback.changed
zone.changed
client.changed
source.changed
queue.changed
library.updated
```

后端事件来源：

- Snapcast JSON-RPC / WebSocket /状态变化
- MPD idle
- AirPlay/DLNA 状态变化

保留 30~60 秒全量状态校准作为兜底。

### 可接受过渡方案

若一期不实现 SSE：

- 区分播放状态轮询与 library collection 请求
- 音量/暂停后不要无条件 `refreshCollections()`
- 状态签名只控制真正必要的 DOM 更新

### 验收标准

普通音量滑动、暂停/播放不会触发无意义的大量曲库请求。

---

# 8. P1 信息架构与页面重构

## UX-01：首页：Now Playing Dashboard

一级导航建议：

```text
首页 / 房间 / 音乐 / 队列 / 设置
```

首页桌面版建议：

```text
┌──────────────────────────────────────────────┐
│ 正在播放                             客厅 ▾   │
│                                              │
│ [Album Art]   歌名                           │
│               歌手 · 专辑                    │
│               ━━━━━●━━━━ 3:12 / 4:08        │
│                 ◀   ▶/Ⅱ   ▶                 │
│               🔊 ━━━━━●━━━━                 │
├──────────────────────────────────────────────┤
│ 播放位置：客厅 + 餐厅              编辑       │
├──────────────────────┬───────────────────────┤
│ 接下来播放            │ 当前音源               │
│ Queue preview         │ Local / AirPlay / DLNA │
└──────────────────────┴───────────────────────┘
```

现有 Now Playing Drawer 可保留，但角色调整为：

- 播放器详情
- 大封面
- 歌词
- 高级播放信息

---

## UX-02：Rooms 页面必须 Group-first

页面主卡片为 Zone/Group，不是单 Client。

默认展开：

- 当前 source
- 当前曲目
- Group volume
- Group 内 client 名称

高级折叠：

- Client volume
- mute
- latency
- 技术信息

不得让 latency 这种工程设置成为视觉主角。

---

## UX-03：Music 页面统一 Library + Playlist

一级导航不再将“歌单”和“曲库”拆成两个产品域。

Music 内二级导航：

```text
专辑 / 歌手 / 曲目 / 歌单 / 文件夹
```

搜索保持常驻或明显入口。

目标：用户思考“我要找音乐”，而不是先判断“这是 Playlist 还是 Library”。

---

## UX-04：移动端 Mini Player 重构

当前 Mini Player + Bottom Nav 不应长期占用约 200px 高度。

建议：

```text
┌──────────────────────────────┐
│ ▣ 歌名 · 歌手          ▶  🔊 │  68~72px
└──────────────────────────────┘
┌──────────────────────────────┐
│ 首页   房间   音乐   队列     │  58~64px
└──────────────────────────────┘
```

顶部 2px 进度条即可。

点击 Mini Player → Fullscreen / Bottom Sheet Now Playing。

支持：

- Album art
- progress
- play/pause/prev/next
- volume
- current zone
- lyrics

---

# 9. P1 视觉系统整改

## VIS-01：建立 Design Token，清理 CSS 补丁链

保留当前视觉方向：

```text
暖黑/深咖背景
奶油白文字
铜橙 accent
大专辑封面
轻微玻璃感
```

建议 CSS 结构：

```text
styles/
  tokens.css
  base.css
  layout.css
  components.css
  player.css
  rooms.css
  music.css
  responsive.css
```

Token 示例：

```css
:root {
  --bg: ...;
  --surface-1: ...;
  --surface-2: ...;
  --text-primary: ...;
  --text-secondary: ...;
  --brand: ...;
  --art-accent: ...;
  --radius-sm: ...;
  --radius-md: ...;
  --shadow-1: ...;
  --space-1: ...;
}
```

要求：

- 不继续新增 `refinements2.css` 之类覆盖补丁
- 逐步把历史样式归并到明确模块
- 源码保持可读，不需要为了几十 KB 手工压成一行

---

## VIS-02：动态封面取色增加可读性约束

### 当前问题

简单 1×1 平均色可能产生脏灰/暗色，并直接污染交互控件对比度。

### 建议算法

```text
封面
 ↓
缩小到 8×8 / 16×16
 ↓
过滤过暗、过亮、低饱和像素
 ↓
weighted dominant color
 ↓
HSL clamp
 saturation >= 35%
 lightness 45%~70%
 ↓
contrast check
 ↓
生成：
 --art-accent
 --art-accent-soft
 --on-art-accent
```

固定品牌色：

```text
--brand
```

动态封面色：

```text
--art-accent
```

两者不得混成同一个全局变量。

---

# 10. P2 交互与细节整改

## UX-05：统一 Dialog / Toast / 主题 / Safe Area

整改项：

1. 移除原生 `prompt()` / `confirm()`；统一使用 `<dialog>` 或自定义 modal。
2. 音量、延迟微调等高频动作成功时不反复弹 Toast；失败时才提示。
3. 支持：
   - 深色
   - 浅色
   - 跟随系统
4. `<meta name="theme-color">` 与实际主题同步。
5. 使用：

```css
env(safe-area-inset-bottom)
```

适配 iPhone Home Indicator。
6. 清理 CSP 与 inline `onerror` 冲突；图片错误处理统一 JS listener。
7. UI 不再硬编码 `192.168.2.125`；改为后端返回 hostname/IP 或显示“本机网关”。

---

## PERF-01：搜索请求取消与竞态治理

搜索框加入 `AbortController`：

- 新查询触发时取消旧查询
- 防止旧响应晚到覆盖新结果
- debounce 可保留

验收：快速输入 `a → ab → abc` 时，不得最终显示 `a` 的旧结果。

---

# 11. 测试任务

## TEST-01：HTTP / 鉴权 / Snapcast 安全边界测试

必须覆盖：

```text
GET /api/state 未登录 → 401
POST /api/player/action 未登录 → 401
登录失败 → 401
登录成功 → 200
Session 失效 → 401
```

Snapcast 网络边界：

```text
127.0.0.1:1780 → reachable
LAN_IP:1780 → unreachable
LAN_IP:1705 → unreachable
LAN_IP:1704 → reachable
```

---

## TEST-02：播放逻辑测试

### Queue

队列：

```text
A / B / C
```

播放 B 后：

```text
A / B / C 仍存在
current = B
```

### Zone source

```text
客厅 = Local
卧室 = AirPlay
```

切换客厅为 DLNA：

```text
客厅 = DLNA
卧室 = AirPlay
```

卧室不得被改变。

---

## TEST-03：路径与输入安全回归

现有安全测试必须保留并继续通过：

- MPD command injection
- library `../` escape
- playlist path escape
- playlist name path injection
- HTTP body size
- static path confinement

不得因架构重构删除安全测试。

---

## TEST-04：Docker Smoke Test

启动真实镜像并至少检查：

- supervisord 所有核心进程存活
- 进程用户正确
- 1781 Web 可访问
- 1780/1705 外部不可访问
- 1704 可访问
- MPD 可用
- Snapserver 可用
- AirPlay 服务能注册
- upmpdcli 能启动

如 CI 环境无法测试 mDNS，可明确标记为 skip，但启动失败不能忽略。

---

# 12. 推荐实施批次

## Phase 1 — 安全与功能正确性

一次 PR/commit 组完成：

- SEC-02
- SEC-03
- UI-03
- UI-04
- 对应测试

原因：改动局部、风险相对可控、收益立刻可见。

## Phase 2 — 认证与 Zone 模型

完成：

- SEC-01
- UI-01
- UI-02
- FE-02
- 对应测试

这是项目架构真正升级的核心批次。

## Phase 3 — 前端重构与页面体系

完成：

- FE-01
- UX-01
- UX-02
- UX-03
- UX-04
- VIS-01

要求：不得只换 HTML/CSS，必须落实新的 Zone state model。

## Phase 4 — 性能、构建与同步

完成：

- OPS-01
- SEC-04
- OPS-02
- FE-03
- PERF-01
- TEST-04

## Phase 5 — 视觉细节与文档

完成：

- VIS-02
- UX-05
- DOC-01

---

# 13. Agent 每个任务的输出格式

每个 Agent 完成一个批次后必须用以下格式汇报：

```markdown
## 完成项
- [x] SEC-xx ...
- [x] UI-xx ...

## 修改文件
- path/to/file: 修改内容

## 关键实现
- ...

## 测试
- command
- result

## 人工验收
- ...

## 兼容风险
- ...

## 未完成/阻塞
- ...
```

不得只说“已完成优化”。

---

# 14. Definition of Done

本轮整改可视为完成，必须同时满足：

- [ ] Web 控制 API 有明确认证边界或用户显式关闭认证
- [ ] Snapcast 1780/1705 不再暴露到 LAN
- [ ] 长期服务尽量以非 root 运行
- [ ] Queue 播放某曲不会清空队列
- [ ] 前端以 Group/Zone 而不是 Client 为一级对象
- [ ] 不同 Zone 可同时使用不同 Source
- [ ] 移动端能够直接播放曲目
- [ ] 首页具备 Now Playing Dashboard
- [ ] Music 统一曲库与歌单导航
- [ ] CSS 有明确 Design Token 和模块边界
- [ ] sourceType/capabilities 由后端返回，不由前端猜测
- [ ] 高频简单操作不触发无意义的全量集合刷新
- [ ] 网络 IP 不再多处写死
- [ ] 大目录扫描与大文件读取有资源保护
- [ ] 基础镜像/关键依赖版本可追踪
- [ ] 安全测试、播放测试、Zone 测试通过
- [ ] README 更新部署、认证、端口、升级与迁移说明

---

# 15. 非目标（本轮不要做）

为避免 Agent 过度重构，本轮明确不要求：

- 不引入 React/Vue/Svelte
- 不引入 Node/NPM 构建链
- 不重写 Python 后端框架
- 不替换 Snapcast
- 不替换 MPD/upmpdcli/Shairport Sync
- 不把 Web UI 做成云服务
- 不新增用户体系/多租户/复杂 RBAC
- 不为了“现代化”强行拆微服务

本项目仍应保持：

> **单容器、局域网优先、低依赖、可在 FNOS/NAS 长期运行。**

---

# 16. 最终产品定位建议

名称可继续沿用仓库名，但产品层面建议统一理解为：

> **FNOS 多房间音乐控制中心 / Multi-room Audio Gateway**

核心产品价值不是“给 Snapcast 加一个网页”，而是：

```text
统一接入 AirPlay / DLNA / 本地 MPD
            ↓
        按 Zone 分发
            ↓
     Snapcast 多房间同步
            ↓
  一个适合手机/桌面的统一控制台
```

整改时一切 UI/架构决策应围绕这个目标，而不是继续叠加独立功能页。
