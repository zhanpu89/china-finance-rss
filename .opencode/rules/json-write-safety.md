# JSON 写入安全

出现 `JSON parsing failed` 时，说明工具调用 payload 格式有误。写入大文件时分多次 `write` 调用，每次不超过 2000 字符。
