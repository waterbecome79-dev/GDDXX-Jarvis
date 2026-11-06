# 在贾维斯上扩展 · Extending Jarvis

贾维斯的每个能力都是一个“工具”：大模型听懂你的话后决定调用哪个工具，工具在本机执行，结果再由大模型说给你听。
加能力 = 加一个工具，不用改主程序。

## 1. 加一个语音能力（插件）

在 `jarvis/plugins/` 新建 `hello.py`：

```python
"""Says hello in a chosen language."""

def greet(lang="en"):
    return {"ok": True, "text": {"en": "Hello", "zh": "你好", "ja": "こんにちは"}.get(lang, "Hello")}

TOOL = {"type": "function", "function": {
    "name": "greet",
    "description": "Return a greeting in a language. Use when the user asks how to say hello in another language.",
    "parameters": {"type": "object", "properties": {"lang": {"type": "string", "description": "en, zh or ja"}}}}}

HINT = " When asked how to say hello in another language, call greet."   # 追加到系统提示词，可为空

def provide():
    return [(TOOL, greet)], HINT
```

plugins 文件夹里的模块会被自动发现。重开贾维斯，说 “Hey Jarvis, how do you say hello in Japanese?”。

可选的钩子：

| 名字 | 作用 |
|---|---|
| `wants(text) -> tool name` | 这句话必须真正执行某个工具（不能只嘴上说），例如全息演示 |
| `bind(ctx)` | 拿到服务的钩子：`ctx.ui(msg)` 发消息给 HUD，`ctx.say_alone(en, zh)` 主动开口，`ctx.narrate(en, zh)` 说完当前这句再说，`ctx.gen()` 对话计数（用户打断时会变） |

规则：工具返回 dict，`ok` 表示成功；说状态之前必须调用工具查（提示词里写清楚）；会动到真实世界的操作（门锁、灶具）不要做成语音工具。
在 `~/.jarvis/config.json` 里 `"plugins": {"hello": false}` 可以关掉一个插件。

## 2. 贾维斯自己学会的技能

做不到的事，贾维斯会记到学习清单。你批准后，它的“大脑”（DeepSeek Harness 插件）会在 `~/.jarvis/lab/skills-trial/` 写一个技能文件夹：
`SKILL.md`（说明）+ `tool.py`（`TOOLS` 列表和 `run(name, args)`）+ `test.json`（测试用例），测试通过、你点安装后才进入 `~/.jarvis/skills/`。
手写技能也是同样的格式。

## 3. 让 HUD 显示新东西

服务和窗口之间是 `ws://127.0.0.1:8765` 上的 JSON 消息。服务端用 `ctx.ui({"type": "my_card", ...})` 发；
窗口在 `hud/js/live.js` 的 `ws.onmessage` 里按 `m.type` 分发，加一个 `else if (m.type === 'my_card') ...`，
界面代码放到 `hud/js/` 里的新文件，并加到 `hud/js/boot.js` 的 `PARTS` 列表（按顺序加载，后面的文件能用前面文件里的变量）。

窗口发给服务的消息：`text`（打字输入）、`interrupt`、`camera`、`listen`（暂停或恢复聆听）、`brain_*`（大脑窗口）、`llm_*`（接入大脑面板）、`earth_*`（地球此刻）、`em_*`（流浪地球计划）、`holo_list` / `holo_show`（3D 拆解库）。

## 4. 加一套皮肤

1. `hud/js/skins.js` 的 `SKINS` 里加一项：颜色角色 `roles`、核心颜色 `core`、可选 `coreKind`。
2. 自己的核心动画：新建 `hud/js/cores/<名字>.js`，定义 `SKCORES.<名字> = function () { ...; return { frame(dt) {}, msg(m) {}, dispose() {} }; }`，
   加进 `boot.js` 的 `PARTS`，再加进 `hud/js/skin-picker.js` 的 `SK_DONE`。
   `frame(dt)` 每帧调用；`msg(m)` 收到服务的每条消息（用 `cores/kit.js` 的 `skEvent(m)` 知道是哪种能力在工作）；`dispose()` 释放几何体和材质。
   动画要跟着状态走：`idle / listening / thinking / speaking`。

## 5. 加一个全息演示

参照 `hud/demos/optimus.js`：模块导出 `install(ctx)`（拿到 `THREE`、`scene`、`camera`），返回带 `command(m)` 和 `state` 的对象；
`hud/js/demos.js` 里 `import()` 它并把消息接上；服务端在 `jarvis/plugins/demos/` 加一个同名工具。
演示素材（照片、视频）放 `hud/media/<演示名>/`，不进 git，用 `manifest.json` 记录来源和许可。

## 6. Mac 和 Windows 的差异

只放在 `jarvis/platforms/`：`mac.py`（Vision 手势和文字识别）、`win.py`（转用 generic 的摄像头、手势、文字识别和打开路径）、`generic.py`（MediaPipe、RapidOCR、OpenCV 摄像头）。
其他代码不要判断操作系统，调用 `platforms.open_path / open_camera / hand_detector / ocr`。

## 测试

```bash
python tests/test_brain.py                 # 大脑 + 接入大脑，假的大模型服务，不需要网络
python tests/simulate_en.py                # 唤醒、打断、追问等 23 个场景（需要模型和 tests/clips_en，见 make_clips_en.py）
python tests/smoke_service.py              # 整个语音服务 + 假声卡
```
