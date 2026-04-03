# GZLib Shelf Finder

Guangzhou Library shelf address finder (local web UI). 通过广州图书馆联合目录 OPAC 进行馆藏位置查询，面向个人快速定位书架/书柜/楼层。

## Features
- 批量查询（一次查多本）
- 多馆藏位置合并展示
- 可借优先排序
- 本地 SQLite 缓存，减少重复请求
- 低依赖：HTML/CSS/JS + Python 标准库 HTTP server

## Dependencies / 环境要求
- Node.js 18/20（含 npm）
- Python 3.10+
- SQLite（随 Python 标准库）
- 当前 requirements.txt 无额外 pip 包（未来新增依赖可直接写入并 `pip install -r requirements.txt`）

## One-click install
```bash
./setup.sh
```
Windows：使用 Git Bash 执行
```bash
bash setup.sh
```

## Run
建议分两个终端运行：

后端服务：
```bash
source .venv/bin/activate
python server.py
```

前端：
```bash
npm start
```

访问：`http://127.0.0.1:8011`

## Project structure
```text
assets/
data/              # 运行时缓存（可清理）
index.html
styles.css
app.js
server.py
setup.sh
requirements.txt
```

## Screenshot（截图）
![UI](assets/ui.png)

## Safety & compliance（安全性与合规性）
- 仅供本地个人使用，不建议对外提供服务/商用。
- 请自行确认广州图书馆/联合目录 OPAC 服务条款（ToS）并遵循其使用限制。
- 内置基础限流（per-IP/per-process），避免过度请求对目标站造成压力；若你的网络环境特殊，请自行调整。
- 默认 SQLite 缓存仅用于加速；可随时删除 data/。
- 该工具不应用于抓取账户信息、登录态数据、敏感个人信息等行为。

## License
MIT
