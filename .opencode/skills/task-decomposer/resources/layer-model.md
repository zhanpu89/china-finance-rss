# 后端分层模型

## 通用分层（单向依赖，上层→下层）

Layer 4 集成层 → Layer 3 接口层 → Layer 2 业务逻辑层 → Layer 1 数据访问层 → Layer 0 基础层

## 语言映射

| 层 | Java | Python | Go | Node.js |
|----|------|--------|----|---------|
| L0 基础 | Entity/Model | Model | Model | Entity |
| L1 数据 | Mapper/Repository | Repository | Repository | Repository |
| L2 业务 | Service | Service | Service | Service |
| L3 接口 | Controller | Router | Handler | Controller |
| L4 集成 | Client/Integration | Client | Client | Client |
