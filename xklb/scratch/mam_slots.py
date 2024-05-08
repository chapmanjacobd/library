from xklb.utils import arggroups, argparse_utils, web


def parse_args():
    parser = argparse_utils.ArgumentParser()
    parser.add_argument("--base-url", default="https://www.myanonamouse.net")
    parser.add_argument("--max", type=int, default=150)

    parser.add_argument("--cookie", required=True)
    arggroups.requests(parser)
    arggroups.debug(parser)

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def get_unsat(args):
    response = web.requests_session(args).get(
        f"{args.base_url}/jsonLoad.php?snatch_summary",
        headers={"Content-Type": "application/json"},
        cookies={"mam_id": args.cookie} if args.cookie else None,
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
