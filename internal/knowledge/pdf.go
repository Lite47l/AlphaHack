package knowledge

import (
    "bytes"
    "context"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "strconv"
    "strings"

    pdf "github.com/ledongthuc/pdf"
)

type PDFPage struct {
    Number int
    Text string
}

func extractPDF(ctx context.Context, path string) ([]PDFPage, error) {
    if strings.ToLower(filepath.Ext(path)) != ".pdf" {
        return nil, fmt.Errorf("file must have .pdf extension")
    }
    file, reader, err := pdf.Open(path)
    if err != nil {
        return nil, fmt.Errorf("open PDF: %w", err)
    }
    defer file.Close()

    pageCount := reader.NumPage()
    pages := make([]PDFPage, 0, pageCount)
    ocrPages := make([]int, 0)
    for n := 1; n <= pageCount; n++ {
        if err := ctx.Err(); err != nil { return nil, err }
        page := reader.Page(n)
        if page.V.IsNull() { ocrPages = append(ocrPages, n); continue }
        text, err := page.GetPlainText(nil)
        if err != nil {
            // Keep the import resilient: OCR this page if text extraction fails.
            ocrPages = append(ocrPages, n)
            continue
        }
        text = strings.TrimSpace(text)
        if text == "" { ocrPages = append(ocrPages, n); continue }
        pages = append(pages, PDFPage{Number:n, Text:text})
    }
    if len(ocrPages) == 0 { return pages, nil }
    ocr, err := extractPagesWithOCR(ctx, path, ocrPages)
    if err != nil { return nil, err }
    pages = append(pages, ocr...)
    // Preserve page order even when only some pages needed OCR.
    for i := 0; i < len(pages); i++ {
        for j := i+1; j < len(pages); j++ {
            if pages[j].Number < pages[i].Number { pages[i], pages[j] = pages[j], pages[i] }
        }
    }
    if len(pages) == 0 { return nil, fmt.Errorf("PDF contains no extractable text after OCR") }
    return pages, nil
}

func extractPagesWithOCR(ctx context.Context, path string, pageNumbers []int) ([]PDFPage, error) {
    tempDir, err := os.MkdirTemp("", "pdf-ocr-*")
    if err != nil { return nil, fmt.Errorf("create OCR temp directory: %w", err) }
    defer os.RemoveAll(tempDir)
    pages := make([]PDFPage, 0, len(pageNumbers))
    for _, n := range pageNumbers {
        if err := ctx.Err(); err != nil { return nil, err }
        prefix := filepath.Join(tempDir, "page")
        // 150 DPI and JPEG reduce CPU, disk and memory compared with 200 DPI PNG.
        cmd := exec.CommandContext(ctx, "pdftoppm",
            "-f", strconv.Itoa(n), "-l", strconv.Itoa(n),
            "-r", "150", "-jpeg", "-singlefile", path, prefix)
        if output, err := cmd.CombinedOutput(); err != nil {
            return nil, fmt.Errorf("render PDF page %d: %w: %s", n, err, strings.TrimSpace(string(output)))
        }
        imagePath := prefix + ".jpg"
        cmd = exec.CommandContext(ctx, "tesseract", imagePath, "stdout", "-l", "rus+eng", "--psm", "3")
        var stdout, stderr bytes.Buffer
        cmd.Stdout, cmd.Stderr = &stdout, &stderr
        if err := cmd.Run(); err != nil {
            return nil, fmt.Errorf("OCR page %d: %w: %s", n, err, strings.TrimSpace(stderr.String()))
        }
        if text := strings.TrimSpace(stdout.String()); text != "" {
            pages = append(pages, PDFPage{Number:n, Text:text})
        }
    }
    return pages, nil
}

func readPDF(path string) ([]byte, error) {
    data, err := os.ReadFile(path)
    if err != nil { return nil, fmt.Errorf("read PDF: %w", err) }
    if len(data) == 0 { return nil, fmt.Errorf("PDF file is empty") }
    return data, nil
}
