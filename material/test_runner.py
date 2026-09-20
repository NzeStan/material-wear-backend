from django.test.runner import DiscoverRunner

from material import cloudinary_test_stub


class OfflineCloudinaryTestRunner(DiscoverRunner):
    """DiscoverRunner that keeps every test off the real Cloudinary account."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        cloudinary_test_stub.start()

    def teardown_test_environment(self, **kwargs):
        cloudinary_test_stub.stop()
        super().teardown_test_environment(**kwargs)
