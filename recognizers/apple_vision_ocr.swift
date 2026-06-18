#!/usr/bin/env swift
import Foundation
import Vision
import ImageIO
import CoreGraphics

struct OCRLine: Encodable {
    let text: String
    let confidence: Float
    let bbox: [Int]
}

struct OCRResult: Encodable {
    let backend: String
    let image_width_px: Int
    let image_height_px: Int
    let lines: [OCRLine]
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

if CommandLine.arguments.count < 2 {
    fail("Usage: apple_vision_ocr.swift IMAGE_PATH", code: 2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let imageSource = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    fail("Could not load image: \(imageURL.path)")
}

let width = image.width
let height = image.height
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(url: imageURL, orientation: .up, options: [:])
do {
    try handler.perform([request])
} catch {
    let nsError = error as NSError
    fail("Apple Vision OCR failed: domain=\(nsError.domain) code=\(nsError.code) description=\(nsError.localizedDescription)")
}

let observations = request.results ?? []
let lines: [OCRLine] = observations.compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else {
        return nil
    }
    let box = observation.boundingBox
    let x0 = Int((box.origin.x * CGFloat(width)).rounded())
    let y0 = Int(((1.0 - box.origin.y - box.height) * CGFloat(height)).rounded())
    let x1 = Int(((box.origin.x + box.width) * CGFloat(width)).rounded())
    let y1 = Int(((1.0 - box.origin.y) * CGFloat(height)).rounded())
    return OCRLine(
        text: candidate.string,
        confidence: candidate.confidence,
        bbox: [x0, y0, x1, y1]
    )
}

let sortedLines = lines.sorted {
    let yDiff = abs($0.bbox[1] - $1.bbox[1])
    if yDiff > 18 {
        return $0.bbox[1] < $1.bbox[1]
    }
    return $0.bbox[0] < $1.bbox[0]
}

let result = OCRResult(
    backend: "apple_vision",
    image_width_px: width,
    image_height_px: height,
    lines: sortedLines
)

let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
do {
    let data = try encoder.encode(result)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fail("Could not encode OCR JSON: \(error)")
}
