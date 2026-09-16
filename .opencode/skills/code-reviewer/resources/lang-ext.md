# 语言特化审查锚点（Lang-Ext）

> 每个语言只列**该语言最容易踩的坑**——不是框架用法科普，是评审时"要特别盯着看"的点。按 LC-001 跳转。

## Java / Spring Boot

- **事务陷阱**：`@Transactional` 的 `this.selfCall()` 不生效（内部调用不走代理）；`@Transactional` 只回滚 RuntimeException，checked 异常需 `rollbackFor`；事务内做网络 IO = 大事务。
- **Optional 滥用**：把 Optional 当 null 检查层层传递，不解决根本。
- **集合**：`ConcurrentModificationException`（遍历中删改）；`HashMap` 并发写丢失更新；使用 `Collectors.toMap` 重复 key 抛异常。
- **MyBatis**：`${}` 拼接 vs `#{}` 参数化（前者注入漏洞）；N+1 查询。
- **异常处理**：`catch (Exception e) { e.printStackTrace() }` 吞异常；`throw new RuntimeException` 无上下文。
- **配置**：魔法配置值散落 vs 统一配置中心；敏感信息明文（密钥放 application.yml）。
- **返回**：实体直接返回前端泄漏字段（用 DTO/View 隔离）。

## Python

- **可变默认参数**：`def f(x=[])` 共享状态 → 累积 bug。
- **浅拷贝陷阱**：`b = a` 是引用，`b = a[:]`/`copy` 才是拷贝；嵌套结构需 `deepcopy`。
- **并发**：GIL 下的线程安全不等于无竞态；`asyncio` 中阻塞调用卡事件循环；共享可变全局状态。
- **异常**：裸 `except:` 吞所有（含 KeyboardInterrupt）；`except Exception` 不记 traceback。
- **SQLAlchemy**：async session 生命周期未管理；N+1（懒加载循环）。
- **Pydantic**：v2 校验不生效场景（未设 `model_config`）；字段默认值可变类型。
- **路径/编码**：文件编码问题；路径拼接用 os.path/Path 而非字符串 `+`。

## Go

- **错误处理**：吞掉 error（`_ = f()`）；error 无包装上下文（无 `%w`）；检查 error 前先用了值。
- **并发**：`map` 并发读写 panic；`go func` 泄漏 goroutine（无退出通道）；`select` 死循环无超时。
- **切片陷阱**：`append` 共享底层数组导致数据覆盖；`s[:]` 引用原数组。
- **指针语义**：循环变量取址（`for i := range` 中 `&x`）指向同一变量。
- **defer**：defer 在循环中累积；defer 中修改返回值需命名返回值。
- **资源**：文件/连接未 `defer Close`；`http.Client` 无超时。
- **日志**：`fmt.Println` 代替结构化日志（zap/logrus）。

## Node.js / TypeScript

- **回调/异步**：Promise 未 await（`fire and forget`）；未捕获 rejection；回调金字塔。
- **浮点陷阱**：`0.1+0.2 !== 0.3`，金额用 decimal 库而非 float。
- **原型/this**：`this` 丢失（回调中）；Object.prototype 污染。
- **内存**：全局变量/闭包持有引用不释放；EventEmitter 监听未移除。
- **安全**：`eval`/`Function` 执行不可信输入；原型链注入（`__proto__`）。
- **日志**：`console.log` 裸输出 vs 结构化（winston/pino）。

## 通用（语言无关但常被忽略）

- **时间/时区**：存储与展示时区不一致；DST 边界；时间计算用库（dayjs/moment）避免手算。
- **编码**：中文乱码（文件编码不一致）。
- **ID 生成**：自增 vs 雪花/UUID；并发下生成冲突。
- **分页**：深分页性能（limit offset 大 offset）；排序不稳定。

> **使用方式**：按 LC-001 只读对应节，不作为科普阅读，而是"评审时对照找坑"。