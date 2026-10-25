// Package migrations встраивает SQL-миграции в бинарник шлюза.
package migrations

import "embed"

// FS содержит файлы *.sql, применяемые по порядку имени.
//
//go:embed *.sql
var FS embed.FS
