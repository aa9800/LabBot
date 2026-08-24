"""2D 시뮬레이션 엔진 — 실제 Raspbot 대신 화면 위에서 움직이는 가상 로봇.

좌표계: 화면 픽셀 기준, (0,0)이 좌상단. 물리는 정밀하지 않지만
라인트래킹 / 초음파 / QR 정지스캔의 '판단 로직'을 연습하는 데는 충분하다.
"""
import math

import pygame

WIDTH, HEIGHT = 900, 600
TRACK_COLOR = (235, 235, 235)
BG_COLOR = (20, 22, 20)
OBSTACLE_COLOR = (200, 90, 40)
MARKER_COLOR = (60, 170, 160)
ROBOT_COLOR = (230, 140, 60)

# 실습실 선반 통로를 흉내낸 순찰 경로 (사각형 루프)
TRACK_POINTS = [
    (150, 150), (750, 150), (750, 450), (150, 450), (150, 150),
]

MARKER_RADIUS = 22


def _path_length(points):
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


def _point_at_fraction(points, frac):
    """경로 전체 길이의 frac(0~1) 지점의 좌표를 구한다. 체크포인트를 균등 배치할 때 쓴다."""
    total = _path_length(points)
    target = total * (frac % 1.0)
    acc = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        seg = math.hypot(bx - ax, by - ay)
        if acc + seg >= target:
            t = (target - acc) / seg if seg else 0
            return (ax + (bx - ax) * t, ay + (by - ay) * t)
        acc += seg
    return points[-1]


def build_markers(items):
    """웹에서 가져온 실제 물품 목록(items)을 위치(location)별로 묶어 체크포인트를 만든다.
    같은 location의 물품은 한 체크포인트에서 한번에 '확인'된다(선반 하나를 통째로 스캔한다고 가정).
    """
    by_location = {}
    for it in items:
        by_location.setdefault(it["location"], []).append(it)
    locations = sorted(by_location.keys())
    n = len(locations)
    markers = []
    for i, loc in enumerate(locations):
        pos = _point_at_fraction(TRACK_POINTS, (i + 0.5) / n) if n else (0, 0)
        markers.append({"pos": pos, "location": loc, "items": by_location[loc]})
    return markers
LINE_SENSOR_SPAN = 18       # 4채널 센서의 좌우 폭(px)
LINE_SENSOR_LOOKAHEAD = 26  # 로봇 앞쪽으로 얼마나 내다보는지(px)
LINE_TOLERANCE = 6          # 트랙 선으로 인정하는 거리(px)
ULTRASONIC_RANGE = 140


def _dist_point_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def distance_to_track(point):
    return min(
        _dist_point_to_segment(point, TRACK_POINTS[i], TRACK_POINTS[i + 1])
        for i in range(len(TRACK_POINTS) - 1)
    )


class Robot:
    def __init__(self):
        self.reset()

    def reset(self):
        self.x, self.y = TRACK_POINTS[0]
        self.heading = 0.0  #도(degree). 0 = 오른쪽을 바라봄
        self.speed = 0.0
        self.turn = 0.0

    def line_sensors(self):
        """4채널 라인 센서를 흉내낸다. [왼쪽, 중앙좌, 중앙우, 오른쪽] 트랙 위 여부(bool)."""
        rad = math.radians(self.heading)
        fx = self.x + math.cos(rad) * LINE_SENSOR_LOOKAHEAD
        fy = self.y + math.sin(rad) * LINE_SENSOR_LOOKAHEAD
        perp = rad + math.pi / 2
        readings = []
        for k in (-1.5, -0.5, 0.5, 1.5):
            sx = fx + math.cos(perp) * k * (LINE_SENSOR_SPAN / 3)
            sy = fy + math.sin(perp) * k * (LINE_SENSOR_SPAN / 3)
            readings.append(distance_to_track((sx, sy)) <= LINE_TOLERANCE)
        return readings

    def ultrasonic(self, obstacles):
        rad = math.radians(self.heading)
        for d in range(4, ULTRASONIC_RANGE, 4):
            px = self.x + math.cos(rad) * d
            py = self.y + math.sin(rad) * d
            for rect in obstacles:
                if rect.collidepoint(px, py):
                    return d
        return ULTRASONIC_RANGE

    def nearby_marker(self, markers):
        for m in markers:
            if math.hypot(self.x - m["pos"][0], self.y - m["pos"][1]) <= MARKER_RADIUS:
                return m
        return None

    def step(self, dt):
        rad = math.radians(self.heading)
        self.x += math.cos(rad) * self.speed * dt
        self.y += math.sin(rad) * self.speed * dt
        self.heading = (self.heading + self.turn * dt) % 360


class World:
    def __init__(self, items=None):
        self.robot = Robot()
        self.obstacles = []  # list[pygame.Rect]
        self.log = []
        self.items = list(items or [])
        self.markers = build_markers(self.items)

    def items_at(self, location):
        """지금 그 위치에 실제로 남아있는(hide_item으로 빼지 않은) 물품들."""
        return [it for it in self.items if it["location"] == location]

    def hide_random_item(self):
        """무작위로 물품 하나를 선반에서 몰래 없앤다 — 실사 불일치 시나리오 연습용."""
        if not self.items:
            return None
        import random

        removed = random.choice(self.items)
        self.items.remove(removed)
        return removed

    def add_obstacle_ahead(self):
        rad = math.radians(self.robot.heading)
        cx = self.robot.x + math.cos(rad) * 70
        cy = self.robot.y + math.sin(rad) * 70
        self.obstacles.append(pygame.Rect(cx - 20, cy - 20, 40, 40))

    def clear_obstacles(self):
        self.obstacles = []

    def note(self, msg):
        self.log.append(msg)
        self.log = self.log[-6:]


def draw(screen, world, font):
    screen.fill(BG_COLOR)
    pygame.draw.lines(screen, TRACK_COLOR, False, TRACK_POINTS, 6)
    for m in world.markers:
        remaining = len(world.items_at(m["location"]))
        pygame.draw.circle(screen, MARKER_COLOR, m["pos"], MARKER_RADIUS, 2)
        label = font.render(f'{m["location"]} ({remaining})', True, MARKER_COLOR)
        screen.blit(label, (m["pos"][0] - label.get_width() // 2, m["pos"][1] - 40))
    for rect in world.obstacles:
        pygame.draw.rect(screen, OBSTACLE_COLOR, rect)

    r = world.robot
    rad = math.radians(r.heading)
    tip = (r.x + math.cos(rad) * 16, r.y + math.sin(rad) * 16)
    pygame.draw.circle(screen, ROBOT_COLOR, (int(r.x), int(r.y)), 12)
    pygame.draw.line(screen, ROBOT_COLOR, (r.x, r.y), tip, 3)

    y = 10
    for line in world.log[::-1]:
        surf = font.render(line, True, (220, 224, 216))
        screen.blit(surf, (10, y))
        y += 20
