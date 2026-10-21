from app.voice import speakable


def test_spells_order_codes():
    assert speakable("Đơn TZ20002 đang giao.") == "Đơn tê dét hai không không không hai đang giao."
    assert speakable("mã tz10003") == "mã tê dét một không không không ba"


def test_leaves_other_text_alone():
    text = "Laptop ASUS bảo hành mười hai tháng."
    assert speakable(text) == text
