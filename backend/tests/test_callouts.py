from cstaktik import callouts


def test_callouts_clock_meters():
    assert callouts.place("TopofMid") == "Top Mid" and callouts.place("BombsiteA") == "A-Site"
    assert callouts.place("SomeNewPlace") == "Some New Place" and callouts.place(None) == ""
    assert callouts.clock(50.7) == "1:04" and callouts.clock(0) == "1:55" and callouts.clock(200) == "0:00"
    assert callouts.clock(90, planted_at=80) == "Bombe 0:30"
    assert callouts.meters(643) == "16 m" and callouts.meters(100) == "2,5 m"
