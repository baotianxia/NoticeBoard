# NoticeBoard

适用于 **Minecraft Java Edition 1.21.11** 与 **MCDReforged (MCDR)** 的原版计分栏（Sidebar）公告栏插件。

完全基于原版指令实现，无需客户端模组；支持全服/指定玩家展示、多页轮播、**显示/隐藏交替**、经典与 RGB 十六进制颜色、动态占位符、配置文件热重载以及 **LuckPerms** 权限节点控制。

---

## ✨ 功能特性

- **原版计分栏渲染**：使用 1.21.5+ SNBT 文本组件与 `numberformat blank`（隐藏右侧红色数字），双缓冲切页零闪烁。
- **灵活的目标过滤**：支持针对**全部玩家**或**部分指定玩家**显示不同页面，也可为特定页面配置排除名单。
- **多页轮播与交替隐藏**：支持多个页面按各自持续时间自动轮播，支持 `hide` 类型页面实现「显示 A 10 秒 → 隐藏 5 秒 → 显示 B 10 秒」的间隔效果。
- **两种轮播模式**：
  - `global`（默认）：全服同步轮播。
  - `per_player`：每位玩家在自己可见的页面之间独立轮播。
- **文件编辑 + 指令管理**：配置保存为单个 JSON 文件，既可直接手动编辑后 `!!board reload` 热重载，也可在游戏内通过指令增删改。
- **权限控制**：同时兼容 **MCDR 权限等级** 与 **LuckPerms 权限节点**（默认 `notice_board.admin`）。
- **丰富颜色与占位符**：支持 `&` 颜色/样式代码及 `&#RRGGBB` RGB 十六进制颜色；内置玩家名、日期、时间、本次在线时长、总在线时长等占位符。
- **控制台防刷屏**：内置 MCDR `InfoFilter`，自动隐藏本插件刷新计分栏时产生的控制台指令回显（需 MCDR `>= 2.13.0`）。
- **OP 聊天防刷屏**：在 `server.properties` 开启 `broadcast-console-to-ops` 时，公告栏运行期间自动临时关闭 `minecraft:log_admin_commands`，停用或卸载插件时自动恢复，避免游戏内 OP 收到 `[Server: ...]` 提示。

---

## 📦 安装方法

1. 确保服务端版本为 **1.21.5 ~ 1.21.11**（推荐 **1.21.11**），MCDR 版本为 **`>= 2.13.0`**（低版本也可运行，但无法自动屏蔽控制台命令回显）。
2. 将单文件插件 **`NoticeBoard.py`** 放入 MCDR 的 `plugins/` 目录。
3. 在 MCDR 控制台执行：
   ```text
   !!MCDR plugin load NoticeBoard.py
   ```
   或重启 MCDR。首次加载后会自动生成配置文件：
   `config/notice_board/config.json`

---

## 🔐 权限配置

默认情况下（`permission.mode = "either"`），以下任一条件满足即可使用管理员指令：
- MCDR 控制台；
- MCDR 权限等级 `>= 3`（`admin` / `owner`）；
- 玩家拥有 LuckPerms 权限节点 **`notice_board.admin`**。

### LuckPerms 授权示例
在服务端或控制台执行：
```text
/lp user <玩家名> permission set notice_board.admin true
```
或给整个管理组授权：
```text
/lp group admin permission set notice_board.admin true
```

> 若希望**只允许** LuckPerms 授权（不参考 MCDR 权限等级），可将配置中的 `permission.mode` 改为 `"luckperms"`。

所有玩家（默认开启 `allow_player_self_toggle: true`）均无需管理权限即可使用 `!!board hide` / `!!board show` 临时隐藏或恢复自己的公告栏。

---

## 🛠️ 指令大全

主指令为 `!!board`（简写别名：`!!ann`）。

### 基础与控制
| 指令                                 | 说明                                                  |
| :----------------------------------- | :---------------------------------------------------- |
| `!!board` / `!!board help`           | 查看指令帮助                                          |
| `!!board list`                       | 查看全局状态与所有页面（点击页面名可查看详情）        |
| `!!board info <页面名>`              | 查看指定页面详情及逐行内容（点击行号可快捷编辑）      |
| `!!board reload`                     | 重新读取 `config/notice_board/config.json` 并立即刷新 |
| `!!board enable` / `!!board disable` | 全局开启 / 关闭公告栏                                 |
| `!!board next` / `!!board prev`      | 立即切换到下一张 / 上一张启用中的页面                 |
| `!!board goto <页面名>`              | 立即跳转到指定页面                                    |
| `!!board mode <global\|per_player>`  | 切换全局同步轮播 / 按玩家独立轮播                     |
| `!!board hide` / `!!board show`      | **玩家个人**隐藏 / 恢复显示公告栏                     |

### 页面增删与属性修改
| 指令                                    | 说明                             |
| :-------------------------------------- | :------------------------------- |
| `!!board add <页面名> <秒数> <标题>`    | 新建一个显示页面（`show`）       |
| `!!board addhide <页面名> <秒数>`       | 新建一个隐藏间隔页面（`hide`）   |
| `!!board remove <页面名>`               | 删除指定页面                     |
| `!!board settitle <页面名> [标题]`      | 修改页面标题（留空可清空标题）   |
| `!!board setduration <页面名> <秒数>`   | 修改页面持续时间（最小 0.5 秒）  |
| `!!board settype <页面名> <show\|hide>` | 修改页面类型为显示或隐藏         |
| `!!board toggle <页面名>`               | 启用 / 禁用单个页面              |
| `!!board move <页面名> <序号>`          | 将页面移动到第 N 位（从 1 开始） |

### 内容行编辑（原版计分栏最多 15 行）
| 指令                                        | 说明                                         |
| :------------------------------------------ | :------------------------------------------- |
| `!!board addline <页面名> [文本]`           | 在末尾追加一行（不填文本或填 `""` 表示空行） |
| `!!board setline <页面名> <行号> [文本]`    | 修改第 N 行（若 N = 当前行数+1 则为追加）    |
| `!!board insertline <页面名> <行号> [文本]` | 在第 N 行前插入一行                          |
| `!!board delline <页面名> <行号>`           | 删除第 N 行                                  |

### 可见目标管理
| 指令                                           | 说明                                       |
| :--------------------------------------------- | :----------------------------------------- |
| `!!board target <页面名> all`                  | 设为对全部玩家可见                         |
| `!!board target <页面名> set <玩家1 玩家2...>` | 设为仅对指定玩家列表可见（空格或逗号分隔） |
| `!!board target <页面名> add <玩家>`           | 向目标列表添加玩家                         |
| `!!board target <页面名> remove <玩家>`        | 从目标列表移除玩家                         |
| `!!board exclude <页面名> add <玩家>`          | 将玩家加入该页的排除名单                   |
| `!!board exclude <页面名> remove <玩家>`       | 将玩家移出排除名单                         |
| `!!board exclude <页面名> clear`               | 清空该页的排除名单                         |

---

## 🎨 颜色与格式

标题与每一行文本均支持以下格式代码（使用 `&` 或 `§` 均可）：

- **经典颜色**：`&0`~`&9`、`&a`~`&f`
- **文字样式**：`&l` 粗体、`&o` 斜体、`&n` 下划线、`&m` 删除线、`&k` 随机字符、`&r` 重置样式
- **RGB 十六进制颜色**：`&#RRGGBB`（例如 `&#FF8800活动公告`）或 `&x&R&R&G&G&B&B`
- **显示普通 `&` 符号**：使用 `&&` 进行转义

---

## 🧩 占位符说明

占位符同时支持 `{名称}` 与 `%名称%` 两种写法：

| 占位符                                    | 说明                                      | 示例输出               |
| :---------------------------------------- | :---------------------------------------- | :--------------------- |
| `{player}` / `{player_name}`              | 当前玩家名称                              | `Steve`                |
| `{date}`                                  | 当前日期（由 `date_format` 控制）         | `2026-11-22`           |
| `{time}`                                  | 当前时间（由 `time_format` 控制）         | `12:30:05`             |
| `{datetime}`                              | 日期 + 时间                               | `2026-11-22 12:30:05`  |
| `{year}` / `{month}` / `{day}`            | 年 / 月 / 日                              | `2026` / `11` / `22`   |
| `{weekday}`                               | 星期（由 `weekdays` 数组控制）            | `周日`                 |
| `{session_time}`                          | 本次上线后的在线时长                      | `15分20秒`             |
| `{session_seconds}` / `minutes` / `hours` | 本次在线秒 / 分 / 小时数                  | `920` / `15` / `0`     |
| `{total_time}`                            | 总在线时长（读取原版 `stats` 并实时累加） | `12小时5分30秒`        |
| `{total_seconds}` / `minutes` / `hours`   | 总在线秒 / 分 / 小时数                    | `43530` / `725` / `12` |
| `{online}` / `{online_count}`             | 当前在线玩家数                            | `8`                    |
| `{page}` / `{total_pages}`                | 当前启用页序号 / 总启用页数               | `1` / `3`              |
| `{show_page}` / `{show_total_pages}`      | 仅计入 `show` 页面的序号 / 总数           | `1` / `2`              |
| `{page_name}`                             | 当前页面名称                              | `welcome`              |

> **小技巧**：如果希望同时减少原版服务端 `logs/latest.log` 的写入量，可将 `time_format` 设为 `"%H:%M"`、将 `duration_format` 设为 `"hm_cn"`，这样页面内容仅在分钟变化时更新一次。

---

## ⚙️ 配置文件说明（`config/notice_board/config.json`）

```json
{
  "enabled": true,
  "suppress_console_output": true,
  "silence_op_feedback": "auto",
  "rotation_mode": "global",
  "refresh_interval": 1.0,
  "skip_empty_targets": true,
  "allow_player_self_toggle": true,
  "date_format": "%Y-%m-%d",
  "time_format": "%H:%M:%S",
  "duration_format": "hms_cn",
  "weekdays": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
  "permission": {
    "mode": "either",
    "mcdr_level": 3,
    "luckperms_node": "notice_board.admin",
    "luckperms_timeout": 1.5
  },
  "team_prefix": "_nb_t_",
  "objective_prefix": "nb_",
  "pages": [
    {
      "name": "welcome",
      "enabled": true,
      "type": "show",
      "duration": 10,
      "targets": "all",
      "exclude": [],
      "title": "&6&l★ 服务器公告 ★",
      "lines": [
        "&7欢迎你, &b{player}",
        "&e时间: &f{time}",
        "&a本次在线: &f{session_time}",
        "&a总计在线: &f{total_time}"
      ]
    },
    {
      "name": "pause_1",
      "enabled": true,
      "type": "hide",
      "duration": 5,
      "targets": "all",
      "exclude": [],
      "title": "",
      "lines": []
    },
    {
      "name": "vip_only",
      "enabled": true,
      "type": "show",
      "duration": 8,
      "targets": ["Steve", "Alex"],
      "exclude": [],
      "title": "&#55FFFF&l专属提示",
      "lines": [
        "&f只有 Steve 和 Alex 能看到这一页"
      ]
    }
  ]
}
```

### 主要配置项说明
- `suppress_console_output`：是否隐藏插件刷新计分栏引起的 MCDR 控制台命令回显（默认 `true`）。
- `silence_op_feedback`：是否防止在线 OP 玩家聊天栏收到 `[Server: ...]` 提示（默认 `"auto"`）：
  - `"auto"`：自动检查 `server.properties` 的 `broadcast-console-to-ops`。若为 `true`，则在公告栏运行期间自动将游戏规则 `minecraft:log_admin_commands` 设为 `false`，并在执行 `!!board disable` 或卸载插件时恢复为 `true`；若已设为 `false`，则不做改动。
  - `"always"`：无论 `server.properties` 如何配置，均在公告栏运行期间自动关闭 `minecraft:log_admin_commands`。
  - `"never"`：不修改该游戏规则（若需保留 OP 指令审计日志，推荐在 `server.properties` 中设置 `broadcast-console-to-ops=false` 后重启服务端）。
- `rotation_mode`：`"global"`（全服统一轮播）或 `"per_player"`（每人独立轮播）。
- `refresh_interval`：刷新检查间隔（秒），默认 `1.0`。
- `skip_empty_targets`：在 `global` 模式下，当某个页面配置的目标玩家当前均不在线时是否自动跳过该页。
- `duration_format`：时长格式化样式：
  - `"hms_cn"`：`1小时2分3秒`
  - `"hm_cn"`：`1小时2分`（精确到分，最省指令）
  - `"hms"`：`1h 2m 3s`
  - `"clock"`：`01:02:03`

---

## 📝 注意事项与兼容性

1. **部分玩家可见 / 个人占位符机制**：
   - 当全服玩家显示的计分栏内容完全一致时，插件直接使用全局 `sidebar`，**不会加入或修改任何原版队伍（Team）**。
   - 当页面仅针对部分玩家、有人使用 `!!board hide` 隐藏，或页面使用了 `{player}` / `{session_time}` / `{total_time}` 等按玩家区分的占位符时，插件会利用原版 `sidebar.team.<color>` 为不同内容组分配临时队伍（默认前缀 `_nb_t_`）。
   - 受 Minecraft 原版机制限制，同一时刻最多同时存在 **16** 种独立显示内容；且如果服务器有其他依赖原版 `/team` 分队颜色的玩法，建议将该玩法与局部公告页面错开，或仅使用无个人占位符的全服公告页。
2. **与 Fuji 的兼容性**：
   - 插件不会干扰 Fuji 的头顶名牌与 Tab 列表模块；总在线时长与原版 `world/stats/<uuid>.json` 中的 `minecraft:play_time` 保持一致。
3. **热卸载清理**：
   - 执行 `!!MCDR plugin unload notice_board` 时，插件会自动清理创建的临时计分项与临时队伍，恢复玩家侧边栏。