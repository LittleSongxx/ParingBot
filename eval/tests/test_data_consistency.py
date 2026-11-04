import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from human_eval import data_consistency  # noqa: E402


def person(**overrides):
    base = {"has_pet": "无", "interest_tags": ["看电影"], "self_intro": "", "roommate_expectation": "",
            "preference": {"detail": {"pet_accept": "接受"}}}
    base.update(overrides)
    return base


class DataConsistencyTest(unittest.TestCase):
    def test_severe_contradiction(self):
        result = data_consistency.assess({"applicant": person(), "candidate": person(
            interest_tags=["养猫", "看电影"], self_intro="我对动物毛发过敏，不能接受宠物")})
        self.assertEqual(result["score"], 0)

    def test_has_pet_and_not_accept(self):
        result = data_consistency.assess({"applicant": person(has_pet="有"),
                                          "candidate": person(has_pet="有", interest_tags=["养狗"],
                                                              preference={"detail": {"pet_accept": "不接受"}})})
        self.assertEqual(result["score"], 0)

    def test_minor_interest_ambiguity(self):
        result = data_consistency.assess({"applicant": person(interest_tags=["养鱼"]),
                                          "candidate": person(has_pet="有", interest_tags=["养猫"])})
        self.assertEqual(result["score"], 1)

    def test_string_interest_tags_are_split(self):
        result = data_consistency.assess({"applicant": person(),
                                          "candidate": person(interest_tags="茶道,养猫,传记",
                                                              preference={"detail": {"pet_accept": "不接受"}})})
        self.assertEqual(result["score"], 0)

    def test_clean_pair(self):
        result = data_consistency.assess({"applicant": person(), "candidate": person()})
        self.assertEqual(result["score"], 2)


if __name__ == "__main__":
    unittest.main()
