class RTOEstimator:
    ALPHA = 1 / 8   # weight of a new sample in SRTT
    BETA = 1 / 4    # weight of a new deviation in RTTVAR
    K = 4           # safety multiplier on RTTVAR

    def __init__(self, initial_rto=0.5, min_rto=0.05, max_rto=5.0, fixed=None):
        self.srtt = None          # no measurement yet
        self.rttvar = None
        self.min_rto = min_rto
        self.max_rto = max_rto
        self.rto = initial_rto
        self.fixed = fixed        # if set, behave as a fixed timeout

    def current_rto(self):
        if self.fixed is not None:
            return self.fixed
        return self.rto

    def _clamp(self, value):
        # keep value between min_rto and max_rto
        return max(self.min_rto, min(value, self.max_rto))

    def on_rtt_sample(self, r):
        if self.fixed is not None:
            return                       # fixed baseline never learns

        if self.srtt is None:
            # first sample: no history yet
            self.srtt = r
            self.rttvar = r / 2
        else:
            # Update RTTVAR first: it needs the OLD srtt
            dev = abs(self.srtt - r)
            self.rttvar = (1 - self.BETA) * self.rttvar + self.BETA * dev
            self.srtt = (1 - self.ALPHA) * self.srtt + self.ALPHA * r

        self.rto = self._clamp(self.srtt + self.K * self.rttvar)

    def on_timeout(self):
        # Exponential backoff: if packets keep vanishing, retry more slowly
        if self.fixed is not None:
            return
        self.rto = self._clamp(self.rto * 2)


if __name__ == "__main__":
    est = RTOEstimator(min_rto=0.0, max_rto=10.0)
    for r in (0.100, 0.140, 0.120):
        est.on_rtt_sample(r)
        print(est.srtt, est.rttvar, est.current_rto())
    est.on_timeout()
    print("after timeout:", est.current_rto())