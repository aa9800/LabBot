"""확장보드에서 배터리 전압을 읽을 수 있는지 찾아본다.

왜 탐색부터 하는가
-----------------
Yahboom 의 YB_Pcb_Car 라이브러리에는 배터리를 읽는 함수가 없다. 보드에 전압
분배 회로가 있고 I2C 레지스터로 노출되는 모델도 있지만, 우리 보드가 그런지는
읽어보기 전에는 알 수 없다.

레지스터를 찍어서 "아마 이거겠지" 하고 화면에 숫자를 띄우면 안 된다. 배터리는
안전에 걸린 정보라, 틀린 값을 보여주는 건 아무 값도 안 보여주는 것보다 나쁘다.
그래서 먼저 훑어보고, 사람이 실제 전압과 대조해서 확인한 뒤에 연결한다.

무엇을 보는가
------------
1. 라이브러리에 배터리 비슷한 함수가 있는지 (있으면 그게 정답이다)
2. I2C 레지스터를 훑어서 7~13V 범위로 해석되는 값이 있는지
   - 2셀 리튬이온이면 6.0~8.4V, 3셀이면 9.0~12.6V
   - 흔한 표현: 100 배 정수(1180 = 11.80V), 10 배 정수(118 = 11.8V), raw ADC

쓰는 법
------
    # 서비스가 I2C 를 잡고 있으면 충돌하므로 먼저 멈춘다
    sudo systemctl stop labkeeper-robot
    python3 probe_battery.py
    sudo systemctl start labkeeper-robot

출력된 후보 중 실제 배터리 전압(멀티미터나 충전기 표시)과 맞는 걸 알려주면
그 레지스터를 코드에 넣는다.
"""

from __future__ import annotations

import sys
import time

I2C_BUS = 1
BOARD_ADDR = 0x16          # YB_Pcb_Car 가 쓰는 확장보드 주소

# 배터리로 볼 만한 전압 범위. 이 밖이면 다른 용도의 레지스터다.
PLAUSIBLE_MIN_V = 5.5
PLAUSIBLE_MAX_V = 13.0


def probe_library():
    """라이브러리에 배터리 함수가 이미 있는지 본다. 있으면 제일 확실하다."""
    print("[1] YB_Pcb_Car 라이브러리 훑기")
    try:
        import YB_Pcb_Car
    except Exception as e:
        print(f"    라이브러리를 못 불러왔다: {e}")
        return None

    names = [n for n in dir(YB_Pcb_Car.YB_Pcb_Car)
             if any(k in n.lower() for k in ("bat", "volt", "adc", "power"))]
    if not names:
        print("    배터리 관련 함수 없음 — 레지스터를 직접 훑어야 한다")
        return None
    print(f"    후보 함수: {names}")
    car = YB_Pcb_Car.YB_Pcb_Car()
    for n in names:
        try:
            print(f"    {n}() -> {getattr(car, n)()}")
        except Exception as e:
            print(f"    {n}() 실패: {e}")
    return names


def interpretations(raw16, lo, hi):
    """한 레지스터 값을 여러 방식으로 전압이라 치고 해석해본다."""
    return {
        "100배 정수(1180=11.80V)": raw16 / 100.0,
        "10배 정수(118=11.8V)": raw16 / 10.0,
        "하위바이트 10배": lo / 10.0,
        "상위바이트 10배": hi / 10.0,
        "바이트순서 뒤집기 /100": ((lo << 8) | hi) / 100.0,
        "ADC 12비트 x 3.3V x 분배3": raw16 / 4095.0 * 3.3 * 3.0,
    }


def probe_registers():
    """I2C 레지스터를 훑어 전압처럼 보이는 값을 찾는다."""
    print("\n[2] I2C 레지스터 훑기 (주소 0x%02X)" % BOARD_ADDR)
    try:
        import smbus
        bus = smbus.SMBus(I2C_BUS)
    except Exception as e:
        print(f"    I2C 를 못 열었다: {e}")
        print("    서비스가 I2C 를 잡고 있으면 먼저 멈추세요:")
        print("      sudo systemctl stop labkeeper-robot")
        return []

    hits = []
    for reg in range(0x00, 0x60):
        try:
            data = bus.read_i2c_block_data(BOARD_ADDR, reg, 2)
        except Exception:
            continue
        hi, lo = data[0], data[1]
        raw16 = (hi << 8) | lo
        if raw16 in (0x0000, 0xFFFF):
            continue        # 빈 레지스터
        for how, volts in interpretations(raw16, lo, hi).items():
            if PLAUSIBLE_MIN_V <= volts <= PLAUSIBLE_MAX_V:
                hits.append((reg, how, volts, raw16))
        time.sleep(0.01)

    if not hits:
        print("    전압처럼 보이는 값이 없다 — 이 보드는 배터리를 안 알려주는 것 같다")
        return []

    print(f"    후보 {len(hits)}개:")
    for reg, how, volts, raw in hits:
        print(f"      0x{reg:02X}  raw={raw:5d}  {how:28s} -> {volts:5.2f}V")
    return hits


def watch(reg, how_index=0):
    """한 레지스터를 계속 읽는다. 값이 안정적인지 보려는 것이다.

    배터리 전압은 천천히 변한다. 초 단위로 요동치면 그건 배터리가 아니라
    다른 센서 값이다.
    """
    import smbus
    bus = smbus.SMBus(I2C_BUS)
    print(f"\n0x{reg:02X} 를 20초간 지켜본다 (Ctrl+C 로 중단)")
    try:
        for _ in range(20):
            data = bus.read_i2c_block_data(BOARD_ADDR, reg, 2)
            raw = (data[0] << 8) | data[1]
            print(f"  raw={raw:5d}  /100={raw / 100.0:5.2f}V  /10={raw / 10.0:5.1f}V")
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main():
    print("배터리 레지스터 탐색\n" + "=" * 46)
    probe_library()
    hits = probe_registers()

    if len(sys.argv) > 1:
        watch(int(sys.argv[1], 0))
        return

    if hits:
        print("\n다음 할 일")
        print("  1) 배터리의 실제 전압을 확인한다(충전기 표시나 멀티미터).")
        print("  2) 위 후보 중 그 값과 맞는 레지스터를 고른다.")
        print("  3) 그 레지스터를 지켜보며 값이 안정적인지 본다:")
        print("       python3 probe_battery.py 0x00   ← 레지스터 번호를 넣어서")
        print("  4) 확인되면 알려주세요. real_hal 에 read_battery() 로 넣겠습니다.")


if __name__ == "__main__":
    main()
