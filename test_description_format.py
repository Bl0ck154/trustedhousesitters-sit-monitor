import unittest
import telegram_action_send as sender

class FormattingTests(unittest.TestCase):
    def test_single_heading_for_many_lines(self):
        data={"title":"Cats","city":"Hamburg","country":"Germany",
              "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/hamburg/hamburg/l/857632/",
              "pets":{"cat":3},"home_type":"apartment",
              "local_attractions":"['city']",
              "responsibilities":"-feed cats\n-clean litter\n-water plants",
              "pet_care":"-clean litter\n-play daily",
              "amenities":{"bedTypes":["double"]}}
        pages=sender.full_description(data)
        text="\n".join(pages)
        self.assertEqual(text.count("Загальна інформація</b>"),1)
        self.assertEqual(text.count("Обов'язки та розпорядок</b>"),1)
        self.assertNotIn("(продовження)",text)
        self.assertNotIn("['city']",text)
        self.assertEqual(text.count("clean litter"),1)
        self.assertIn("двоспальне ліжко",text)
        self.assertTrue(all(len(p)<4096 for p in pages))

if __name__=="__main__": unittest.main()
