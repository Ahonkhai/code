import os
import unittest
from unittest.mock import patch

import bot


class ApplePayTests(unittest.TestCase):
    def test_get_apple_pay_urls_returns_configured_checkout_links(self):
        with patch.dict(
            os.environ,
            {
                "APPLE_PAY_URL": "https://apple.example/checkout",
                "PAYMENT_URL_1": "https://pay.example/one",
                "PAYMENT_URL_2": "https://pay.example/two",
            },
            clear=False,
        ):
            urls = bot.get_apple_pay_urls()

        self.assertEqual(
            urls,
            [
                "https://apple.example/checkout",
                "https://pay.example/one",
                "https://pay.example/two",
            ],
        )

    def test_get_apple_pay_urls_returns_empty_list_without_configuration(self):
        with patch.dict(
            os.environ,
            {
                "APPLE_PAY_URL": "",
                "PAYMENT_URL_1": "",
                "PAYMENT_URL_2": "",
            },
            clear=False,
        ):
            urls = bot.get_apple_pay_urls()

        self.assertEqual(urls, [])
