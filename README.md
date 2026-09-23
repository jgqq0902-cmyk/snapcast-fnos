# Snap / Room

面向 FNOS 与通用 Docker 主机的单容器多房间音频网关，Powered by Snapcast。镜像内集成 Snapserver、AirPlay 1、DLNA Media Renderer、MPD、myMPD 播放器和精简设备控制台。

## 能力与边界

- AirPlay 接收器：`Snapcast-AirPlay`（Shairport Sync）
- DLNA Media Renderer：`Snapcast-DLNA`（upmpdcli + MPD）
- myMPD 提供本地曲库、队列、歌单、封面和本地歌词
- 按播放区域控制音源、音量、静音和客户端延迟
- `Default` Meta 流按 `Airplay/DLNA` 顺序选择，AirPlay 优先
- 不连接在线元数据、图标 CDN、遥测或外部管理服务
- DLNA 远程 HTTP/HTTPS 音源经过容器内回环续传代理；CDN 提前断开时使用字节 Range 从中断位置恢复

## 网络与安全

所有 LAN、宿主路径、容器名称和 Web 端口都在 `.env` 配置。下表用 `<网关地址>` 表示你为 macvlan 分配的地址：

| 接口 | 地址 | 可见范围 |
| --- | --- | --- |
| 统一控制台与 myMPD | `http://<网关地址>:1781/` | LAN，默认需要登录 |
| Snapclient 音频 | `<网关地址>:1704` | LAN |
| AirPlay | `<网关地址>:5000` 及动态端口 | LAN/mDNS |
| DLNA | `<网关地址>` | LAN/SSDP |
| myMPD 内部服务 | `127.0.0.1:1782` | 仅容器内部，由 `/player/` 代理 |
| Snapserver HTTP/JSON-RPC | `127.0.0.1:1780` | 仅容器内部 |
| Snapserver TCP control | `127.0.0.1:1705` | 仅容器内部 |
| DLNA HTTP 续传与 MPD 代理 | `127.0.0.1:1790/6601` | 仅容器内部 |

1780 和 1705 不再对 LAN 开放，避免绕过 Web 控制台鉴权。旧 Snapweb 因此不再作为外部入口；统一入口是 1781。仅在完全可信且隔离的家庭 LAN 中，才可将 `CONTROL_AUTH_ENABLED=false`。

登录在 nginx 按真实客户端地址限流，Control 只在 TCP 对端为 loopback 时信任 `X-Real-IP`。默认使用 HTTP，适合隔离的家庭 LAN；如网络包含访客或不可信设备，可将证书放入 `CERTS_DIR` 并设置：

```env
WEB_TLS_ENABLED=true
TLS_CERT=/app/certs/fullchain.pem
TLS_KEY=/app/certs/privkey.pem
```

启用后统一入口使用 `https://<网关地址>:1781/`，会话 Cookie 自动增加 `Secure`。

## 首次部署

1. 在 FNOS 准备项目并创建环境配置：

```sh
cd /path/to/snapcast-fnos
cp .env.example .env
chmod 600 .env
```

2. 编辑 `.env`：

- `GATEWAY_IP`、`LAN_SUBNET`、`LAN_GATEWAY`、`MACVLAN_PARENT` 必须匹配实际 LAN。
- `CONFIG_DIR`、`DATA_DIR`、`CERTS_DIR` 和 `MEDIA_ROOT` 指向宿主持久化目录；默认前三项使用项目内相对路径。
- `CONTROL_PASSWORD` 必须改为较长且唯一的密码，不要提交 `.env`。
- `PUID`/`PGID` 应能读取曲库并写入项目的 `data` 目录。默认 `1000:1001` 适配 `/vol1/1000/music` 的当前 FNOS 权限；可用 `stat -c '%u:%g %a %n' /vol1/1000/music` 核实。

3. 校验、构建并启动：

```sh
docker compose config -q
docker compose build
mkdir -p config data certs
cp snapserver.conf config/snapserver.conf
docker compose up -d --wait --wait-timeout 180
docker exec snapcast /app/unified/smoke-test.sh
```

冒烟测试包含未认证拦截、登录、myMPD 静态资源、WebSocket Upgrade 和退出后会话失效的完整生产代理链验证。

`MEDIA_ROOT` 会只读挂载为容器内 `/media`。控制台和播放器不会修改音乐文件。持久化目录 `config/`、`data/`、`certs/`、`.env` 均已从 Git 排除。

也可在已经运行旧版本时使用部署脚本。它会备份运行配置与旧镜像，校验密码，构建、切换并执行冒烟测试：

```sh
sh unified/deploy-console.sh
```

## 从旧版本迁移

1. 先备份 `docker-compose.yml`、`config/`、`data/` 和当前镜像。
2. 从 `.env.example` 创建 `.env`，设置网络、`PUID/PGID` 和控制台密码。
3. 将仓库的 `snapserver.conf` 复制到 `config/snapserver.conf`；仅改 Compose 不会更新已挂载的运行时配置。
4. 重建单容器。Snapclient 应连接 `.env` 中的 `GATEWAY_IP:1704`。
5. 登录统一入口的设备页检查音源、音量和延迟，再打开同站点 `/player/` 检查曲库、封面、歌词、队列和歌单。

认证会话保存在内存中，容器重启或会话到期后需要重新登录。登录失败具有按来源地址的短时限速。

## 验证

本地快速检查：

```sh
python -m unittest control.test_app -q
python -m unittest unified.test_dlna_relay -v
node --check control/static/app.js
node --check control/static/js/api.js
node --check control/static/js/store.js
node --check control/static/js/ui.js
node --check control/static/js/zones.js
docker compose config -q
```

容器内检查：

```sh
docker exec snapcast /app/unified/smoke-test.sh
```

从同一 LAN 的另一台机器检查网络边界：

```sh
nc -vz "$GATEWAY_IP" 1704       # 应成功
nc -vz "$GATEWAY_IP" 1705       # 应失败
nc -vz "$GATEWAY_IP" 1780       # 应失败
nc -vz "$GATEWAY_IP" 1782       # 应失败（myMPD 不再裸露）
GATEWAY_IP="$GATEWAY_IP" python unified/verify_discovery.py
```

另需人工验证：iPhone 可发现 AirPlay、DLNA 控制端可发现设备并连续切集、S12/R1 同步发声、390/768/1440px 页面无横向溢出、触屏操作目标易于点击。

## 回滚

部署脚本失败时会自动恢复旧镜像和运行时 Snapserver 配置。手工回滚时使用脚本输出的备份标签：

```sh
docker image tag snapcast-all-in-one:backup-YYYYMMDD-HHMMSS snapcast-all-in-one:local
cp backups/YYYYMMDD-HHMMSS-audit-remediation/snapserver.runtime.conf config/snapserver.conf
docker compose up -d --remove-orphans --wait --wait-timeout 180
```

不要删除 `data/`；其中包含 MPD 数据库、歌单、曲库配置和 Snapcast 的 `server.json`。

## 可复现构建与升级

基础镜像固定为已验证 digest；Alpine 软件源使用国内可达的清华镜像并保留 APK 签名校验。关键音频包固定为：MPD `0.24.15-r0`、myMPD `25.3.0-r0`、upmpdcli `1.9.17-r1`。构建会输出这些软件与 nginx 的实际版本。

升级依赖时单独提交变更：先确认新 digest 和包版本，在测试环境完成单元测试、镜像构建、容器冒烟、AirPlay/DLNA 发现与连续播放，再更新固定值。不要改回 `latest` 或无版本约束。

## Web 结构

1781 的 Snap / Room 控制台采用原生 ES Modules，默认进入设备页，负责 Snapcast 音源、音量、静音、延迟、设备重命名与播放组管理：

- `control/static/js/`：API、状态、设备、播放组与通用 UI
- `control/static/styles/`：令牌、基础、布局、设备卡片与响应式样式
- `control/static/icons/`：本地 SVG Sprite；来源和许可见 `NOTICE.md`

“播放器”页通过同源 `/player/` 全屏嵌入未修改的 myMPD，并保留重新加载和新窗口打开入口。myMPD 只监听容器回环地址，访问统一受控制台会话保护；其状态持久化在 `data/mympd`，并连接同容器内的 MPD Unix socket。

设备页的“立即停止”会停止 MPD（保留队列）并断开当前 AirPlay 会话，不会修改任何设备的音量、静音、延迟或播放组。AirPlay 优先使用 Shairport Sync 的 D-Bus `DropSession`；接口不可用时由固定的无参数辅助脚本终止接收进程，Supervisor 随即恢复接收服务。

upmpdcli 只连接回环 MPD 命令代理 `127.0.0.1:6601`。代理仅改写 DLNA 提交的 HTTP/HTTPS 播放地址，本地曲库和 myMPD 仍直接连接 MPD `6600`。对应的 HTTP 续传服务只监听 `127.0.0.1:1790`，不会成为 LAN 通用代理；上游连接提前结束时按当前字节位置重试，默认最多连续重试 10 次并采用退避等待。带签名 URL 已失效、源站不允许续传或控制端主动停止时不会伪造成功。

控制台以 WCAG 2.2 AA 为验收基线：浅色主题的小号强调文字使用独立高对比度铜棕色；主导航和音源选择暴露当前 ARIA 状态；登录弹窗不可通过 ESC 或背景点击关闭。退出登录或会话过期会立即清空设备、音源及播放器 iframe。设备页对连接中、空设备、网关离线、部分设备离线和会话失效分别提供明确状态与恢复入口。

前端发布前应在浅色和深色主题下检查 `1440×900`、`1280×720`、`1024×768`、`900×1200`、`768×1024`、`430×932`、`390×844`、`375×812` 与 `320×568`；至少覆盖空设备、在线、部分离线、长名称、登录和会话过期状态。`control.test_app.ProductionConfigTest` 固化对比度、ARIA、认证清理、状态文案和移动端布局契约，避免常见视觉回归。
