# Snapcast FNOS 音源网关

面向 FNOS 的单容器多房间音频网关。一个镜像内集成 Snapserver、AirPlay 1、DLNA Media Renderer、MPD 本地播放器和移动端 Web 控制台。

## 功能

- AirPlay 1 接收器：Shairport Sync
- DLNA Media Renderer：upmpdcli + MPD
- 本地曲库、播放队列、歌单导入与导出
- Snapcast 设备音量、静音、音源和延迟补偿控制
- AirPlay 优先的 `Default` Meta 流
- 响应式 Web 控制台
- 单 Docker 容器部署和健康检查

## 默认网络

示例 Compose 使用 macvlan：

- 网段：`192.168.2.0/24`
- 网关：`192.168.2.8`
- 父接口：`eno2-ovs`
- 容器地址：`192.168.2.125`
- Web 控制台：`http://192.168.2.125:1781/`
- Snapcast：TCP `1704`、`1705`、`1780`
- AirPlay：TCP `5000`

部署到其他网络前，请修改 `docker-compose.yml` 中的网段、网关、父接口和静态地址。

## FNOS 部署

```sh
cd /vol1/1000/tools/snapcast
docker compose config
docker compose build
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

默认只读挂载 `/vol1/1000` 到容器 `/media`。持久化配置、运行数据和证书分别位于项目目录的 `config`、`data` 和 `certs`，这些目录不会提交到 Git。

## 测试

```sh
python -m unittest control.test_app -q
node --check control/static/app.js
```

## 第三方资源

控制台图标的来源和许可信息见 `control/static/icons/NOTICE.md`。项目没有加载外部图标 CDN、遥测或在线元数据服务。
