# 技术选型参考

## 评估维度

成熟度/性能/可扩展性/运维复杂度/成本/团队技术储备

## 技术目录（简）

- 后端框架：Java Spring Boot / Python FastAPI / Go Gin / Node.js NestJS
- 数据库：MySQL 8.0 / PostgreSQL 14+ / TiDB / Redis 7+
- 消息队列：RocketMQ / RabbitMQ / Kafka
- 前端：Vue3 + Pinia / React + Zustand（见 LC-FE-001）

## SAD 层协作边界

- system-architect：选型论证、核心表+关键字段（非 DDL）、端点列表（非 OpenAPI Schema）
- task-decomposer：完整 DDL（第 6 节）、完整 OpenAPI 3.0（第 3 节）
