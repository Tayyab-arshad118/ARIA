import argparse
import httpx

from .config import Settings


def main():
    parser = argparse.ArgumentParser(description="Update the running A.R.I.A backend without restarting")
    parser.add_argument("command", choices=["set-colab-url"])
    parser.add_argument("url", help="New HTTPS trycloudflare origin")
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--update-key", action="store_true", help="Also read COLAB_API_KEY from .env/environment")
    args = parser.parse_args()
    settings = Settings()
    headers = {"Authorization": "Bearer " + settings.aria_key.get_secret_value()} if settings.aria_key.get_secret_value() else {}
    body = {"colab_url": args.url}
    if args.update_key:
        body["colab_api_key"] = settings.colab_api_key.get_secret_value()
    try:
        response = httpx.post(args.backend.rstrip("/") + "/api/admin/colab-url", headers=headers,
                              json=body, timeout=30, follow_redirects=False, trust_env=False)
        if response.status_code != 200:
            parser.exit(1, f"Update failed (HTTP {response.status_code}); check URL and backend authentication.\n")
    except httpx.HTTPError:
        parser.exit(1, "Backend unreachable; start it and check --backend.\n")
    print("Colab configuration updated and persisted. No restart needed.")


if __name__ == "__main__":
    main()
