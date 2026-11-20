from bist_mcp.teknik import destek_direnc, hareketli_ortalama, macd, rsi


def test_surekli_yukselen_seride_rsi_100e_yakin():
    assert rsi([float(i) for i in range(1, 40)]) > 95


def test_surekli_dusen_seride_rsi_sifira_yakin():
    assert rsi([float(i) for i in range(40, 1, -1)]) < 5


def test_yetersiz_veride_rsi_none():
    assert rsi([1.0, 2.0, 3.0]) is None


def test_hareketli_ortalama_son_n_kapanisin_ortalamasi():
    # Son 2 kapanis [30, 40] -> 35; tum seri -> 25
    assert hareketli_ortalama([10.0, 20.0, 30.0, 40.0], 2) == 35.0
    assert hareketli_ortalama([10.0, 20.0, 30.0, 40.0], 4) == 25.0


def test_yetersiz_veride_hareketli_ortalama_none():
    assert hareketli_ortalama([10.0, 20.0], 5) is None


def test_macd_yukselen_seride_pozitif():
    sonuc = macd([float(i) for i in range(1, 60)])
    assert sonuc["macd"] > 0


def test_yetersiz_veride_macd_none():
    assert macd([1.0, 2.0]) is None


def test_destek_direnc_en_dusuk_ve_en_yuksegi_bulur():
    mumlar = [
        {"yuksek": 110.0, "dusuk": 90.0},
        {"yuksek": 120.0, "dusuk": 85.0},
        {"yuksek": 105.0, "dusuk": 95.0},
    ]
    assert destek_direnc(mumlar) == {"destek": 85.0, "direnc": 120.0}


def test_bos_mum_listesinde_destek_direnc_none():
    assert destek_direnc([]) == {"destek": None, "direnc": None}
