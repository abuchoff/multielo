import numpy as np
import pandas as pd
from pandas import DataFrame
import logging
from .multielo import MultiElo
from .config import defaults


class Player:
    """
    The Player object stores the current and historical ratings of an individual player (or team, etc.). Attributes of
    interest are Player.rating (the current rating) and Player.rating_history (a list of historical ratings).
    """

    def __init__(
        self,
        player_id,
        rating=defaults["INITIAL_RATING"],
        rating_history=None,
        date=None,
    ):
        """
        Instantiate a player.

        :param player_id: player ID (e.g., the player's name)
        :type player_id: str
        :param rating: player's current rating
        :type rating: float
        :param rating_history: history of player's ratings (each entry is a (date, rating) tuple); if None, create
        the first entry in the player's history
        :type rating_history: list
        :param date: date of this rating (e.g., player's first matchup date)
        :type date: str
        """
        self.id = player_id
        self.rating = rating
        if rating_history is None:
            self.rating_history = []
            self._update_rating_history(rating, date)
        else:
            self.rating_history = rating_history

    def update_rating(self, new_rating, date=None):
        """
        Update a player's rating and rating history. (updates the self.rating and self.rating_history attributes)

        :param new_rating: player's new rating
        :type new_rating: float
        :param date: date the new rating was achieved
        :type date: str
        """
        self.rating = new_rating
        self._update_rating_history(rating=new_rating, date=date)

    def get_rating_as_of_date(self, date, default_rating=defaults["INITIAL_RATING"]):
        """
        Retrieve a player's rating as of a specified date. Finds an entry in self.rating history for the latest
        date less than or equal to the specified date. If there are multiple entries on that date, take the
        one corresponding to a game result.

        :param date: as-of-date to get a player's rating
        :type date: str
        :param default_rating: the default rating to return for dates before the earliest date in the player's
        rating history (i.e., the default rating for new players)
        :type default_rating: float

        :return: player's rating as of the specified date
        :rtype: float
        """
        history_df = DataFrame(self.rating_history, columns=["date", "rating"])

        # only select one entry per distinct date
        history_df["r"] = history_df.groupby(["date"]).rank(method="first", ascending=False)
        history_df = history_df[history_df["r"] == 1]

        # get the rating for the latest date
        history_df = history_df[history_df["date"] <= date].sort_values("date", ascending=False)
        if history_df.shape[0] == 0:
            return default_rating
        else:
            return history_df.reset_index().loc[0, "rating"]

    def count_games(self):
        """
        Counts games played by this Player.
        """
        return len(self.rating_history) - 1

    def _update_rating_history(self, rating, date):
        """
        Update a player's rating history (self.rating_history)

        :param rating: player's new rating effective on this date
        :type rating: float
        :param date: effective date for new rating
        :type date: str
        """
        self.rating_history.append((date, rating))

    def __str__(self):
        return f"{self.id}: {round(self.rating, 2)} ({self.count_games()} games)"

    def __repr__(self):
        return f"Player(id = {self.id}, rating = {round(self.rating, 2)}, n_games = {self.count_games()})"

    def __eq__(self, other):
        return self.rating == other

    def __lt__(self, other):
        return self.rating < other

    def __le__(self, other):
        return self.rating <= other

    def __gt__(self, other):
        return self.rating > other

    def __ge__(self, other):
        return self.rating >= other


class Tracker:
    """
    The Tracker object can be used to track rating changes over time for a group of players (or teams, etc.) with
    multiple matchups against each other. The tracker stores and updates a dataframe of Player objects (in
    Tracker.player_df) and those Player objects store the rating histories for the individual players.
    """

    def __init__(
        self,
        elo_rater=MultiElo(),
        initial_rating=defaults["INITIAL_RATING"],
        player_df=None,
        logger=None,
    ):
        """
        Instantiate a tracker that will track player's ratings over time as matchups occur.

        :param elo_rater:
        :type elo_rater: MultiElo
        :param initial_rating: initial rating value for new players
        :type initial_rating: float
        :param player_df: dataframe of existing players. New players will be added to the dataframe when they
        appear in a matchup for the first time. If None, begin with no players in the dataframe.
        :type player_df: DataFrame
        """
        self.elo = elo_rater
        self.initial_player_rating = initial_rating

        if player_df is None:
            player_df = DataFrame(columns=["player_id", "player"], dtype=object)

        self.player_df = player_df
        self._validate_player_df()

        self.logger = logger or logging.getLogger()
        logging.basicConfig()

    def process_data(self, matchup_history_df, date_col="date"):
        """
        Process the full matchup history of a group of players. Update the ratings and rating history for all
        players in found in the matchup history.

        :param matchup_history_df: dataframe of matchup history with a column for date and one column for each
        possible finishing place (e.g., "date", "1st", "2nd", "3rd", ...). Finishing place columns should be in
        order of first to last.
        :type matchup_history_df: DataFrame
        :param date_col: name of the date column
        :type date_col: str
        """
        matchup_history_df = matchup_history_df.sort_values(date_col).reset_index(drop=True)
        place_cols = [x for x in matchup_history_df.columns if x != date_col]
        matchup_history_df = matchup_history_df.dropna(how="all", axis=0, subset=place_cols)  # drop rows if all NaN
        for _, row in matchup_history_df.iterrows():
            date = row[date_col]
            players = [self._get_or_create_player(row[x]) for x in place_cols if not pd.isna(row[x])]
            initial_ratings = np.array([player.rating for player in players])
            new_ratings = self.elo.get_new_ratings(initial_ratings)
            for i, player in enumerate(players):
                player.update_rating(new_ratings[i], date=date)

            # log rating changes at INFO level
            msg = f"{date}: "
            for i, player in enumerate(players):
                msg += f"{player.id}: {round(initial_ratings[i], 2)} --> {round(player.rating, 2)}; "
            self.logger.info(msg)

    def get_current_ratings(self):
        """
        Retrieve the current ratings of all players in this Tracker.

        :return: dataframe with all players' ratings and number of games played
        :rtype: DataFrame
        """
        df = self.player_df.copy()
        df["rating"] = df["player"].apply(lambda x: x.rating)
        df["n_games"] = df["player"].apply(lambda x: x.count_games())
        df = df.sort_values("player", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, df.shape[0] + 1)
        df = df[["rank", "player_id", "n_games", "rating"]]
        return df

    def get_history_df(self):
        """
        Retrieve the rating history for all players in this Tracker.

        :return: dataframe with all players' ratings on each date that they changed
        :rtype: DataFrame
        """
        history_df = DataFrame(columns=["player_id", "date", "rating"])
        history_df["rating"] = history_df["rating"].astype(float)

        players = [player for player in self.player_df["player"]]
        for player in players:
            # check if there are any missing dates after the first entry (the initial rating)
            if any([x[0] is None for x in player.rating_history[1:]]):
                self.logger.warning(f"WARNING: possible missing dates in history for Player {player.id}")

            player_history_df = DataFrame(player.rating_history, columns=["date", "rating"])
            player_history_df = player_history_df[~player_history_df["date"].isna()]
            player_history_df["player_id"] = player.id
            history_df = pd.concat([history_df, player_history_df], sort=False)

        return history_df.reset_index(drop=True)

    def retrieve_existing_player(self, player_id):
        """
        Retrieve a player in the Tracker with a given ID.

        :param player_id: the player's ID
        :type player_id: str

        :return: the Player object associated with the provided ID
        :rtype: Player
        """
        if player_id in self.player_df["player_id"].tolist():
            player = self.player_df.loc[self.player_df["player_id"] == player_id, "player"].tolist()[0]
            return player
        else:
            raise ValueError(f"no player found with ID {player_id}")

    def _get_or_create_player(self, player_id):
        if player_id in self.player_df["player_id"].tolist():
            return self.retrieve_existing_player(player_id)
        else:
            return self._create_new_player(player_id)

    def _create_new_player(self, player_id):
        # first check if the player already exists
        if player_id in self.player_df["player_id"].tolist():
            raise ValueError(f"a player with ID {player_id} already exists in the tracker")

        # create and add the player to the database
        player = Player(player_id, rating=self.initial_player_rating)
        add_df = DataFrame({"player_id": [player_id], "player": [player]})
        self.player_df = pd.concat([self.player_df, add_df])
        self._validate_player_df()
        self.logger.info(f"created player with ID {player_id}")
        return player

    def _validate_player_df(self):
        if not self.player_df["player_id"].is_unique:
            raise ValueError("Player IDs must be unique")

        if not all([isinstance(x, Player) for x in self.player_df["player"]]):
            raise ValueError("The player column should contain Player objects")

        self.player_df = self.player_df.sort_values("player_id").reset_index(drop=True)

    def __repr__(self):
        return f"Tracker({self.player_df.shape[0]} total players)"


if __name__ == "__main__":
    import doctest
    doctest.testmod()
