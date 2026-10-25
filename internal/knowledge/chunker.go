package knowledge

import (
	"strings"
	"unicode"
)

type Chunk struct {
	PageNumber int
	Index      int
	Content    string
}

func splitText(pageNumber int, text string, maxRunes int) []Chunk {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}

	if maxRunes < 1 {
		maxRunes = 1500
	}

	runes := []rune(text)
	chunks := make([]Chunk, 0)

	for start, index := 0, 0; start < len(runes); index++ {
		end := start + maxRunes
		if end >= len(runes) {
			end = len(runes)
		} else {
			for i := end; i > start; i-- {
				if unicode.IsSpace(runes[i-1]) {
					end = i
					break
				}
			}
		}

		content := strings.TrimSpace(string(runes[start:end]))
		if content != "" {
			chunks = append(chunks, Chunk{
				PageNumber: pageNumber,
				Index:      index,
				Content:    content,
			})
		}

		start = end
	}

	return chunks
}
