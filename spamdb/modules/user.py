import bson
import random
from datetime import datetime, timedelta
from modules.seed import env
from modules.event import events
import modules.perf as perf
import modules.util as util
from typing import Tuple


def update_user_colls() -> None:
    args = env.args
    db = env.db

    if args.drop:
        db.perf_stat.drop()
        db.user_perf.drop()
        db.pref.drop()
        db.ranking.drop()
        db.history4.drop()
        db.user4.drop()

    users: list[User] = []
    patrons: list[Patron] = []
    rankings: list[perf.Ranking] = []
    perfstats: list[perf.PerfStat] = []
    userperfs: list[perf.UserPerfs] = []
    history: list[History] = []

    follow_factor = args.follow

    for uid in env.uids:
        users.append(User(uid))
        perfs, stats = users[-1].detach_perfs()
        userperfs.append(perf.UserPerfs(uid, perfs))
        history.append(History(userperfs[-1], users[-1].createdAt))
        for stat in stats:
            perfstats.append(stat)
            rankings.append(stat.get_ranking())
        env.fide_map[uid] = users[-1].profile["fideRating"]

    for u in users:
        for f in random.sample(env.uids, int(follow_factor * len(env.uids))):
            events.follow(u._id, util.time_since(u.createdAt), f)
        if u.plan["active"]:
            patrons.append(Patron(u._id))

    users.extend(_create_special_users())

    if args.no_create:
        return

    util.bulk_write(db.pref, [Pref(u._id) for u in users])
    util.bulk_write(db.user4, users)
    util.bulk_write(db.plan_patron, patrons)
    util.bulk_write(db.ranking, rankings)
    util.bulk_write(db.perf_stat, perfstats)
    util.bulk_write(db.user_perf, userperfs)
    util.bulk_write(db.history4, history)


class User:
    def __init__(
        self,
        name: str,
        marks: list[str] = [],
        roles: list[str] = [],
        with_perfs: bool = True,
    ):
        self._id = util.normalize_id(name)
        self.username = name.capitalize()
        self.email = f"lichess.waste.basket+{name}@gmail.com" # sorry google
        self.bpass = bson.binary.Binary(env.get_password_hash(name))
        self.enabled = True
        self.createdAt = util.time_since_days_ago()
        self.seenAt = util.time_since(self.createdAt)
        self.lang = "en-US"
        self.time = {"total": util.rrange(10000, 20000), "tv": 0}
        self.roles = []
        self.roles.extend(roles)
        self.marks = marks
        if util.chance(0.1):
            self.title = random.choice(_titles)
        self.plan = {
            "months": 1,
            "active": util.chance(0.2),
            "since": util.time_since_days_ago(30),
        }
        rating = min(3000, max(int(random.normalvariate(1700, 300)), 400))
        self.profile = {
            "country": env.random_country(),
            "location": self.username + " City",
            "bio": env.random_paragraph(),
            "firstName": self.username,
            "lastName": self.username + "bertson",
            "fideRating": rating,
            "uscfRating": util.rrange(rating - 200, rating + 200),
            "ecfRating": util.rrange(rating - 200, rating + 200),
            "rcfRating": util.rrange(rating - 200, rating + 200),
            "cfcRating": util.rrange(rating - 200, rating + 200),
            "dsbRating": util.rrange(rating - 200, rating + 200),
            "links": "\n".join(env.random_social_media_links()),
        }
        total_games = util.rrange(2000, 10000)
        total_wins = total_losses = total_draws = 0

        if with_perfs: # TODO: move this into perfstat.py
            self.perfStats = {}
            self.perfs = {}
            perf_games: list[int] = util.random_partition(total_games, len(perf.types), 0)

            for [index, perf_name, draw_ratio], num_games in zip(perf.types, perf_games):
                if num_games == 0:
                    continue
                p = perf.PerfStat(self._id, index, num_games, draw_ratio, rating)

                total_wins = total_wins + p.count["win"]
                total_losses = total_losses + p.count["loss"]
                total_draws = total_draws + p.count["draw"]
                self.perfStats[perf_name] = p
                self.perfs[perf_name] = {
                    "nb": p.count["all"],
                    "la": util.time_since_days_ago(30),
                    "re": [util.rrange(-32, 32) for _ in range(12)],
                    "gl": {
                        "r": p.r,
                        "d": random.uniform(0.5, 120),
                        "v": random.uniform(0.001, 0.1),
                    },
                }
        else:
            total_games = 0

        self.count = {
            "game": total_games,
            "ai": 0,
            "rated": int(total_games * 0.8),
            "win": total_wins,
            "winH": total_wins,
            "loss": total_losses,
            "lossH": total_losses,
            "draw": total_draws,
            "drawH": total_draws,
        }

    def detach_perfs(
        self,
    ) ->Tuple[dict, list[perf.PerfStat]]:
        detached_list = list(self.perfStats.values())
        detached_perfs = self.perfs
        delattr(self, "perfStats")
        delattr(self, "perfs")
        return (detached_perfs, detached_list)


class Patron:
    def __init__(self, uid: str):
        patronedAt = util.time_since_days_ago(30)
        lifetime = util.chance(0.5)

        self._id = uid
        self.expiresAt = patronedAt + timedelta(days=30) if not lifetime else None
        self.free = {
            "at": patronedAt,
        }
        self.lastLevelUp = patronedAt
        self.lifetime = lifetime


class Pref:
    def __init__(self, uid: str):
        self._id = uid
        self.is3d = False  # completely mandatory
        self.bg = env.user_bg_mode
        self.bgImg = env.random_bg_image_link()
        self.agreement = 2
        self.submitMove = 0


class History:
    def __init__(self, ups: perf.UserPerfs, since: datetime):
        self._id = ups._id
        for (name, perf) in vars(ups).items():
            if name.startswith("_"):
                continue
            newR = perf["gl"]["r"]
            origR = min(3000, max(400, util.rrange(newR - 500, newR + 500)))
            ratingHistory = {}
            days: int = (datetime.now() - since).days
            for x in range(0, days, util.rrange(2, 10)):
                intermediateR = int(origR + (newR - origR) * x / max(days, 1))
                ratingHistory[str(x)] = util.rrange(intermediateR - 100, intermediateR + 100)
            setattr(self, name, ratingHistory)


def _create_special_users():
    users: list[User] = []
    users.append(User("lichess", [], ["ROLE_SUPER_ADMIN"], False))
    users.append(User("superadmin", [], ["ROLE_SUPER_ADMIN"], False))
    users[-1].title = "LM"
    users.append(User("admin", [], ["ROLE_ADMIN"], False))
    users.append(User("shusher", [], ["ROLE_SHUSHER"], False))
    users.append(User("hunter", [], ["ROLE_CHEAT_HUNTER"], False))
    users.append(User("puzzler", [], ["ROLE_PUZZLE_CURATOR"], False))
    users.append(User("api", [], ["ROLE_API_HOG"], False))
    users.append(User("troll", ["troll"], [], False))
    users.append(User("rankban", ["rankban"], [], False))
    users.append(User("reportban", ["reportban"], [], False))
    users.append(User("alt", ["alt"], [], False))
    users.append(User("boost", ["boost"], [], False))
    users.append(User("engine", ["engine"], [], False))
    users.append(User("coach", [], ["ROLE_COACH"], False))
    users.append(User("teacher", [], ["ROLE_TEACHER"], False))
    users.append(User("kid", [], [], False))
    users[-1].kid = True
    for i in range(10):
        users.append(User(f"bot{i}", [], [], False))
        users[-1].title = "BOT"
    users.append(User("w"*20, [], [], False))
    users[-1].username = "W"*20  # widest possible i think
    users[-1].title = "WGM"
    users[-1].plan["active"] = True  # patron
    users[-1].plan["months"] = 12
    return users


_titles: list[str] = [
    "GM",
    "WGM",
    "IM",
    "WIM",
    "FM",
    "WFM",
    "NM",
    "CM",
    "WCM",
    "WNM",
    # "BOT",
    # "LM",
]
