from capturekarma.motion.ticker import Ticker


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_ticks_count_and_normalised_time():
    c = FakeClock()
    tk = Ticker(hz=10, clock=c.now, sleep=c.sleep)
    out = list(tk.ticks(1.0))
    assert [i for i, _ in out] == list(range(1, 11))
    assert out[-1][1] == 1.0 and abs(out[4][1] - 0.5) < 1e-9
    assert abs(c.t - 101.0) < 1e-6  # advanced exactly one second


def test_min_one_tick():
    c = FakeClock()
    assert Ticker(hz=10, clock=c.now, sleep=c.sleep).n_ticks(0.0) == 1
    assert len(list(Ticker(hz=10, clock=c.now, sleep=c.sleep).ticks(0.0))) == 1


def test_late_tick_catches_up_without_sleeping():
    c = FakeClock()
    tk = Ticker(hz=10, clock=c.now, sleep=c.sleep)
    gen = tk.ticks(0.5)
    next(gen)          # tick 1 at +0.1
    n_before = len(c.sleeps)
    c.t += 0.35        # simulate a stall past ticks 2,3,4
    next(gen); next(gen); next(gen)
    assert c.sleeps[n_before:] == []   # late ticks never sleep
    i, t = next(gen)   # tick 5 at +0.5; only ~0.05 remains to sleep
    assert i == 5 and t == 1.0
    assert abs(c.t - 100.5) < 1e-6


def test_now_uses_injected_clock():
    c = FakeClock()
    assert Ticker(hz=10, clock=c.now, sleep=c.sleep).now() == 100.0


def test_wait_advances_clock():
    c = FakeClock()
    Ticker(hz=10, clock=c.now, sleep=c.sleep).wait(0.3)
    assert abs(c.t - 100.3) < 1e-6
