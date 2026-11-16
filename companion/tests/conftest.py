def pytest_addoption(parser):
    parser.addoption(
        "--api-key-file", help="Explicit raw key file for opt-in synthetic live tests"
    )
    parser.addoption(
        "--native-office",
        action="store_true",
        help="Create disposable Word/WPS documents for real COM integration tests",
    )
    parser.addoption(
        "--live-model",
        action="store_true",
        help="Use the configured model on synthetic data; native Office tests also require --native-office",
    )
