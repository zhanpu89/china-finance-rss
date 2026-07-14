# 语言测试模式（参考）

按 LC-001 跳转。仅提供项目特有约定，标准语法 AI 已知。

## Java

测试框架：JUnit 5 + Mockito + MockMvc。DAO 测试用 `@DataJpaTest` + H2，Service 用 `@ExtendWith(MockitoExtension.class)`，Controller 用 `@WebMvcTest` + `MockMvc`。

## Python

测试框架：pytest + httpx。Manager 用 `pytest.fixture` mock 依赖，API 用 `httpx.AsyncClient`。

## Node.js

测试框架：Jest + Supertest。`__tests__/` 目录，`*.test.ts` 命名。Supertest 发 HTTP 请求测 API。

## Go

测试框架：testing + testify。`*_test.go` 命名，suite 组织，httptest 测 handler。
