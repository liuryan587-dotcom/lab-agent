import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("LLM_MODEL", "test-model")


import pytest
from app.common.exceptions import BusinessException
from app.services.reservation_service import find_free_slots, max_overlap


def test_empty_existing_returns_all_slots():
    result = find_free_slots([], 480, 600, duration=60, step=10)
    assert result["slots"] == [480, 490, 500, 510, 520, 530, 540]


def test_zero_duration_raise_400():
    with pytest.raises(BusinessException) as exc_info:
        find_free_slots([], 480, 600, duration=0, step=10)
    assert exc_info.value.code == 400


def test_touching_reservation_is_allowed():
    existing = [(600, 660)]  # 10:00 AM to 11:00 AM
    result = find_free_slots(existing, 480, 1260, duration=60, step=10)
    assert 660 in result["slots"]  # 11:00 AM is allowed


def test_buffer_blocks_back_to_back_start():
    result = find_free_slots([(600, 660)], 480, 1260, duration=60, step=10, buffer=10)
    assert 660 not in result["slots"]


def test_buffer_allows_exact_gap():
    result = find_free_slots([(600, 660)], 480, 1260, duration=60, step=10, buffer=10)
    assert 670 in result["slots"]  # 间距正好 10


def test_open_range_too_short_returns_empty():
    result = find_free_slots([], 480, 510, duration=60, step=10)
    assert result["slots"] == []  # Not enough time for a 60-minute slot


def test_open_start_after_open_end_raises_400():
    with pytest.raises(BusinessException) as exc_info:
        find_free_slots([], 600, 480, duration=60, step=10)
    assert exc_info.value.code == 400


def test_exact_overlap_is_rejected():
    result = find_free_slots([(600, 660)], 480, 1260, duration=60, step=10)
    assert 600 not in result["slots"]


def test_lab_capacity_allows_multiple_people():
    # capacity=2：09:00-10:00 已有一人，10:00-11:00 已有一人
    # 新约 09:30-10:30 时,任一时刻最多 2 人 → 应该允许
    result = find_free_slots(
        [(540, 600), (600, 660)], 480, 720, duration=60, step=10, capacity=2
    )
    assert 570 in result["slots"]  # 09:30


def test_max_overlap_is_zero_without_reservations():
    assert max_overlap([], 480, 600) == 0


def test_max_overlap_counts_two_overlapping():
    assert max_overlap([(540, 600), (540, 600)], 480, 660) == 2


def test_max_overlap_touching_is_one():
    assert (
        max_overlap([(540, 600), (600, 660)], 480, 720) == 1
    )  # 首尾相接，峰值是 1 不是 2


def test_slots_before_earliest_are_excluded():
    # 现在 14:39 = 879；step=10，因此第一个可约是 880（14:40）
    result = find_free_slots([], 480, 1260, duration=60, step=10, earliest=879)
    assert result["slots"][0] == 880


def test_earliest_after_open_end_returns_empty():
    result = find_free_slots([], 480, 600, duration=60, step=10, earliest=590)
    assert result["slots"] == []
