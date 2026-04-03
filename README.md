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
- 当前 requirements.txt 无额外 pip 包（未来新增依赖可直接写入并 pip install）

## One-click install
```bash
./setup.sh
```
Windows：使用 Git Bash 执行 `bash setup.sh`

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
```
assets/
data/              # 运行时缓存（可清理）
index.html
styles.css
app.js
server.py
setup.sh
requirements.txt
README.md
```

## Screenshot（截图）
![UI](assets/ui.png)

## Disclaimer
本项目仅用于学习与个人使用；请自行确保使用方式符合目标站点/服务条款与当地法律法规。

## License
MIT
