import Foundation
import Vision
import AppKit

// usage: swift ocr.swift <png>... ; prints JSON {file: text}
var result: [String: Any] = [:]
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["ru-RU", "en-US"]
    req.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    try? handler.perform([req])
    let obs = (req.results ?? [])
    // sort top-to-bottom, then left-to-right; keep reading order of columns roughly
    let lines = obs.compactMap { o -> (CGRect, String)? in
        guard let t = o.topCandidates(1).first?.string else { return nil }
        return (o.boundingBox, t)
    }
    let rows: [[String: Any]] = lines.map { l in
        ["x": l.0.minX, "y": 1 - l.0.maxY, "w": l.0.width, "h": l.0.height, "t": l.1]
    }
    result[(path as NSString).lastPathComponent] = rows
}
let data = try! JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
