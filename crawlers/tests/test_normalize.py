from normalize import normalize_decision


class TestNormalizeDecision:
    def test_ad_word(self):
        assert normalize_decision("AD小奖") == ("Offer", None)

    def test_offer(self):
        assert normalize_decision("Offer") == ("Offer", None)

    def test_grad_not_misjudged(self):
        # bug 回归："graduate" 含 "ad" 子串但不是 Offer
        assert normalize_decision("graduate program info") == ("Other", None)

    def test_conditional(self):
        assert normalize_decision("Conditional Offer") == ("Offer", "Conditional")
        assert normalize_decision("con offer 雅思还差0.5") == ("Offer", "Conditional")
        assert normalize_decision("有条件录取") == ("Offer", "Conditional")

    def test_unconditional_checked_before_con(self):
        # "uncon" 含 "con" 子串，必须先判 uncon
        assert normalize_decision("Unconditional Offer") == ("Offer", "Unconditional")
        assert normalize_decision("uncon了") == ("Offer", "Unconditional")

    def test_rejected(self):
        assert normalize_decision("Rejected") == ("Rejected", None)
        assert normalize_decision("拒信") == ("Rejected", None)

    def test_waitlist_interview_other(self):
        assert normalize_decision("WL") == ("Waitlist", None)
        assert normalize_decision("interview invite") == ("Interview", None)
        assert normalize_decision("") == ("Other", None)

    def test_con_substring_not_misjudged(self):
        # "con"子串误判回归: congratulations/economics 不是 con offer
        assert normalize_decision("congratulations") == ("Other", None)
        assert normalize_decision("economics offer from lse") == ("Offer", None)

    def test_wl_substring_not_misjudged(self):
        # "wl"子串误判回归: owl 不是 waitlist
        assert normalize_decision("owl") == ("Other", None)

    def test_reject_with_tiaojian_not_offer(self):
        # 拒信文本含"条件"不得被 detail 短路成 Offer
        assert normalize_decision("拒信，条件不符") == ("Rejected", None)
        assert normalize_decision("reject: conditions not met") == ("Rejected", None)
