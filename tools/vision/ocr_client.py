from __future__ import annotations
from pathlib import Path
import cv2
import re
from rapidocr_onnxruntime import RapidOCR
from core.schemas import BoundingBox

# 全局单例OCR实例
_ocr = None

def get_ocr_client():
    global _ocr
    if _ocr is None:
        _ocr = RapidOCR()
    return _ocr

def ocr_image(image_path: str | Path, roi_bbox: BoundingBox | None = None) -> list[tuple[BoundingBox, str, float]]:
    """
    对图片进行OCR识别，返回识别结果
    :param image_path: 图片路径
    :param roi_bbox: 可选，只在指定区域内识别
    :return: list of (bbox, text, confidence)
    """
    ocr = get_ocr_client()
    img = cv2.imread(str(image_path))
    if img is None:
        return []

    # 裁剪ROI区域
    if roi_bbox:
        x1, y1, x2, y2 = int(roi_bbox.x1), int(roi_bbox.y1), int(roi_bbox.x2), int(roi_bbox.y2)
        # 确保坐标在图片范围内
        h, w = img.shape[:2]
        x1 = max(0, min(x1, w-1))
        y1 = max(0, min(y1, h-1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        img = img[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1
    else:
        offset_x, offset_y = 0, 0

    # 执行OCR
    result, _ = ocr(img)
    if not result:
        return []

    # 转换为标准格式
    ocr_results = []
    for box_points, text, confidence in result:
        # box_points是[[x1,y1], [x2,y1], [x2,y2], [x1,y2]]格式
        xs = [p[0] for p in box_points]
        ys = [p[1] for p in box_points]
        bbox = BoundingBox(
            x1=round(min(xs)) + offset_x,
            y1=round(min(ys)) + offset_y,
            x2=round(max(xs)) + offset_x,
            y2=round(max(ys)) + offset_y
        )
        ocr_results.append((bbox, text.strip(), float(confidence)))

    return ocr_results

def _normalize_text(text: str) -> str:
    return re.sub(r"[\s，,。；;：:'\"“”‘’「」『』（）()【】\[\]\-_/\\|·•]+", "", (text or "").lower())


def _expand_bbox(bbox: BoundingBox, image_path: str | Path, pad_x: int = 24, pad_y: int = 12) -> BoundingBox:
    img = cv2.imread(str(image_path))
    if img is None:
        return bbox
    h, w = img.shape[:2]
    return BoundingBox(
        x1=max(0, bbox.x1 - pad_x),
        y1=max(0, bbox.y1 - pad_y),
        x2=min(w, bbox.x2 + pad_x),
        y2=min(h, bbox.y2 + pad_y),
    )


def _union_bbox(items: list[BoundingBox]) -> BoundingBox:
    return BoundingBox(
        x1=min(item.x1 for item in items),
        y1=min(item.y1 for item in items),
        x2=max(item.x2 for item in items),
        y2=max(item.y2 for item in items),
    )


def match_text_in_region(image_path: str | Path, target_text: str, roi_bbox: BoundingBox | None = None, threshold: float = 0.6) -> tuple[BoundingBox | None, str, float]:
    """
    在指定区域内匹配目标文本
    :param image_path: 图片路径
    :param target_text: 要匹配的目标文本
    :param roi_bbox: 搜索区域
    :param threshold: 匹配阈值（0-1）
    :return: (匹配到的bbox, 匹配文本, 置信度)，未匹配到返回(None, "", 0.0)
    """
    results = ocr_image(image_path, roi_bbox)
    if not results:
        return None, "", 0.0

    target_norm = _normalize_text(target_text)
    if not target_norm:
        return None, "", 0.0
    best_match = None
    best_score = 0.0
    best_text = ""

    for bbox, text, confidence in results:
        text_norm = _normalize_text(text)
        if not text_norm:
            continue
        if target_norm in text_norm or text_norm in target_norm:
            overlap = min(len(target_norm), len(text_norm)) / max(len(target_norm), len(text_norm), 1)
            score = float(confidence) * max(0.72, overlap)
            if score > best_score and score >= threshold:
                best_score = score
                best_match = _expand_bbox(bbox, image_path)
                best_text = text

    return best_match, best_text, best_score


def match_text_row_in_region(
    image_path: str | Path,
    target_text: str,
    roi_bbox: BoundingBox | None = None,
    threshold: float = 0.52,
    row_y_tolerance: int = 34,
) -> tuple[BoundingBox | None, str, float]:
    """Match target text and return the surrounding row-like bbox for safer clicks."""
    results = ocr_image(image_path, roi_bbox)
    target_norm = _normalize_text(target_text)
    if not results or not target_norm:
        return None, "", 0.0

    best: tuple[BoundingBox, str, float] | None = None
    best_score = 0.0
    for bbox, text, confidence in results:
        text_norm = _normalize_text(text)
        if not text_norm:
            continue
        if target_norm in text_norm or text_norm in target_norm:
            overlap = min(len(target_norm), len(text_norm)) / max(len(target_norm), len(text_norm), 1)
            score = float(confidence) * max(0.72, overlap)
            if score >= threshold and score > best_score:
                best = (bbox, text, score)
                best_score = score

    if best is None:
        return None, "", 0.0

    match_bbox, match_text, score = best
    cy = (match_bbox.y1 + match_bbox.y2) // 2
    row_boxes = [
        bbox
        for bbox, _text, _confidence in results
        if abs(((bbox.y1 + bbox.y2) // 2) - cy) <= row_y_tolerance
    ]
    row_bbox = _union_bbox(row_boxes or [match_bbox])
    if roi_bbox:
        row_bbox = BoundingBox(
            x1=max(roi_bbox.x1, min(row_bbox.x1, roi_bbox.x2)),
            y1=max(roi_bbox.y1, min(row_bbox.y1, roi_bbox.y2)),
            x2=max(roi_bbox.x1, min(row_bbox.x2, roi_bbox.x2)),
            y2=max(roi_bbox.y1, min(row_bbox.y2, roi_bbox.y2)),
        )
    return _expand_bbox(row_bbox, image_path, pad_x=36, pad_y=16), match_text, score
