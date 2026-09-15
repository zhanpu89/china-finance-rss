# 语言测试锚点（Lang-Test-Patterns）

> 每个语言给**可操作的测试手法**：框架选型、mock 边界、数据策略、易错点。不是语法科普，是"现在开始写，写对"的手册。按 LC-001 跳转。

## Java / JUnit 5 + Mockito + MockMvc

- **分层测试策略**：DAO 用 `@DataJpaTest` + H2（真实 SQL，验映射）；Service 用 `@ExtendWith(MockitoExtension.class)` mock 依赖；Controller 用 `@WebMvcTest` + `@MockBean` + MockMvc。
- **mock 边界**：mock 的是"依赖"（Redis/第三方/事务无关 Repository），**不要 mock 被测对象本身**；`when(...).thenReturn` 只对依赖返回配置的值。
- **事务/回滚验证**：断言 `@Transactional` 的 `rollbackFor`、`@TransactionalEventListener`；事务边界用 `@Transactional` 测试观察回滚。
- **数据策略**：`@DataJpaTest` 默认回滚，多次运行不污染；集成测试用 `@Sql(scripts=...)` 建基线，`@Transactional` + `Rollback` 隔离。
- **并发**：`ExecutorService` 多线程发并发写，断言不丢更新（验证乐观锁）。

## Python / pytest + httpx

- **fixture 隔离 mock**：`pytest.fixture` 里 `mocker.patch` 依赖；`scope="function"` 每次重建，`scope="session"` 慎用（共享可变状态）。
- **异步测试**：`pytest.mark.asyncio` + `httpx.AsyncClient`（TestClient 不带 asyncio 语义）；`asyncio.gather` 并发发请求。
- **DB/数据**：测试用独立库/事务回滚 fixture；工厂函数建隔离数据；时间依赖用 `freezegun`/monkeypatch 时钟。
- **断言**：异常断言 `pytest.raises(ValueError, match=...)` 必须匹配具体 code；不要裸 `pytest.raises(Exception)`。
- **参数化**：`@pytest.mark.parametrize` 一个测试多个边界值，避免重复代码。

## Node.js / Jest + Supertest

- **mock 模块**：`jest.mock('./dep')` mock 依赖；`jest.fn()` 断言调用参数/次数；`beforeEach` 清 `mockClear` 避免用例间污染。
- **异步**：异步用例必须 `await` 或返回 Promise，否则 Jest 静默通过假绿；`jest.useFakeTimers` 控制定时器/超时。
- **HTTP 测试**：Supertest 起 app 发请求；避免真实网络（mock 对外依赖）。
- **数据**：测试库/内存库（Sqlite in-memory）基建线；`afterEach` 清理数据。
- **模块命名**：`__tests__/` 或 `*.test.ts`；一致性用 `testPathPattern`。

## Go / testing + testify

- **表驱动测试**：`[]struct{name, input, want, wantErr}` + `t.Run(name, ...)`，一个测试跑多组输入。
- **mock**：抽象接口 + testify `mock.Mock` 或 gomock 生成 stub；`mock.Anything` 慎用，尽量精确匹配入参。
- **并发**：`t.Parallel()` 并行用例，注意共享外设要隔离；`sync.WaitGroup` 并发测试。
- **HTTP**：`httptest.NewServer`/`httptest.NewRecorder` 测 handler，不真实端口。
- **断言**：`assert.NoError` / `require.NoError`（require 立即终止，assert 继续）；`assert.Equal(t, want, got, "说明")`。
- **数据**：`sqlmock`mock DB；集成用真实 DB + 事务隔离，测试尾 `tx.Rollback`。

## mock 与数据策略的通用铁律（跨语言）

1. **mock 依赖，不 mock 自己**：被测对象内部逻辑必须真实执行，mock 的是边界依赖（网络/DB/第三方/时间）。
2. **避免 mock 链过深**：mock 超过 3 层 = 测试在测 mock，不在测逻辑，重构系统。
3. **数据隔离**：单元测试 fixture 建隔离数据，完成即清；集成需独立库 + 可重建基线。
4. **时间/随机**：注入时钟与随机源（fake/jest.useFakeTimers/freezegun），杜绝时间敏感 flaky。
5. **断言具象**：断言具体返回/code/字段，不裸断言"无异常"。