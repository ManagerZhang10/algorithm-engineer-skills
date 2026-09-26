# 素材：从哪来、怎么转、放哪

全部本地化到 `deck/media/`（视频多就开 `media/video/`）。deck 里**不引外链**——
双击 `deck.html` 断网也要能看，别人拿到这个文件夹也要能看。

## 论文 / 报告里的图

矢量图（PDF）转位图，别截屏：

```bash
# 正文插图 300 dpi 够；细节多的、tikz 画的用 400–600
pdftoppm -r 400 -png -singlefile paper/figures/overview.pdf media/overview
```

已经是 png/jpg 的原样拷贝，别重新压一遍。转完在 `media/` 里用看得懂的名字
（`c3_overview.png`、`cp_actioncond.png`），并在 `说明.md` 里写清它是第几张图——
半年后回来改页面时这是唯一能对上的线索。

裁白边、拼图用 PIL（macOS 默认没有 `pdfcrop`）：

```python
from PIL import Image
im = Image.open("media/hook.png")
im.crop((0, 0, im.width, int(im.height*0.72))).save("media/hook.png")   # 裁掉下方留白

# 四列两行拼一张（上排预测 / 下排真值这种）
ims=[Image.open(f"media/cmp_{k}.jpg") for k in ["p1","p2","p3","p4","g1","g2","g3","g4"]]
w,h=ims[0].size; sheet=Image.new("RGB",(w*4,h*2),"white")
for i,t in enumerate(ims): sheet.paste(t,((i%4)*w,(i//4)*h))
sheet.save("media/cmp_grid.png")
```

## 视频

原片先放 `素材源/`（不进 deck 目录），切好的片段才进 `media/`：

```bash
# deck 里是静音循环播，不需要音轨
ffmpeg -ss 22.5 -to 47.5 -i 素材源/official.mp4 -an \
  -c:v libx264 -crf 23 -pix_fmt yuv420p media/demo_clip.mp4
```

- 单个片段 10–90 秒，讲到这页时正好循环一两遍。
- 整段演示片（3–5 分钟）用满屏 `.film` 页 + `controls`，自己控制播放进度。
- 网页上的视频 `yt-dlp <url>` 拿原片。
- 视频太大不适合进仓库时，用 `ffmpeg -ss 3.2 -i x.mp4 -frames:v 1 media/poster_x.png`
  抽一帧做静态页，或改成外链加载（那就不再是离线可用，自己权衡）。

## 网页截图

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --hide-scrollbars --virtual-time-budget=6000 --window-size=1600,1000 \
  --screenshot=media/shot_hn.png "https://example.com/page"
```

截图页用 `.fig.plain`（圆角、不加白卡内边距），或 `.grid4` 里的 `.ph`
（裁切填满 + 左下角 `.tag` 标名字）。

## 封面那条图带

封面底部 `.cover .photos` 是 330px 高的横条，五张图 `object-fit:cover` 平分宽度。
选图：**五张各代表这次讲的一个部分**，按讲解顺序排。太竖的图会只剩中间一条，优先挑横构图。

```bash
ffmpeg -ss 3.2 -i media/video/demo.mp4 -frames:v 1 media/cover_3.png   # 视频截帧
```

## 进 deck 之后

跑一遍 `render_preview.py` 看缩略图（SKILL.md 里的自查回路）。重点看：
图糊不糊（dpi 给低了）、白卡是不是空了一大半（图太竖，考虑换 `.fig2` 或裁）、
**截图里有没有不该露的东西**（个人信息、别的标签页、内部路径、没打码的人脸）——
deck 会被录进视频或发出去，这一步比版式重要。
