import argparse

from xklb.utils import objects, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--base-url", default="https://www.myanonamouse.net")
    parser.add_argument("--max", type=int, default=150)

    parser.add_argument("--cookie", required=True)
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def get_unsat(args):
    response = web.requests_session().get(
        f"{args.base_url}/jsonLoad.php?snatch_summary",
        headers={"Content-Type": "application/json"},
        cookies={"mam_id": args.cookie},
    )
    response.raise_for_status()
    data = response.json()

    unsat = data["unsat"]["count"]
    return unsat


def mam_slots():
    args = parse_args()

    try:
        unsat = get_unsat(args)
        print(args.max - unsat)
    except Exception:
        if args.verbose == 0:
            print(0)
        else:
            raise


if __name__ == "__main__":
    mam_slots()
