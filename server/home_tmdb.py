"""32.5: fileiras do TMDB (listas de 32.2 cruzadas com o acervo). Sem TMDB_API_KEY ou sem itens do servidor na lista, a fileira some."""
from itertools import chain, zip_longest

from server import tmdb_lists
from server.db import get_db
from server.home_rows import poster_items, row


def _make(row_key, list_key, title):
    @row(row_key, title)
    def provider(ctx):
        tmdb_lists.ensure_fresh()  # 1º acesso sem cache: busca em segundo plano, sem travar o Início
        with get_db() as conn:
            return poster_items(conn, ctx, tmdb_lists.matches(conn, ctx.user_id, list_key, limit=40))
    return provider


_make("tmdb_movie_now_playing", "movie_now_playing", "home.row.now_playing")
_make("tmdb_tv_airing_today", "tv_airing_today", "home.row.airing_today")
_make("tmdb_tv_on_the_air", "tv_on_the_air", "home.row.on_the_air")
_make("tmdb_movie_popular", "movie_popular", "home.row.movie_popular")
_make("tmdb_tv_popular", "tv_popular", "home.row.tv_popular")
_make("tmdb_movie_top_rated", "movie_top_rated", "home.row.movie_top_rated")
_make("tmdb_tv_top_rated", "tv_top_rated", "home.row.tv_top_rated")


@row("tmdb_trending", "home.row.trending")
def trending(ctx):
    """Filmes e séries em alta, intercalados pela posição no TMDB."""
    tmdb_lists.ensure_fresh()
    with get_db() as conn:
        a = tmdb_lists.matches(conn, ctx.user_id, "trending_movie", limit=40)
        b = tmdb_lists.matches(conn, ctx.user_id, "trending_tv", limit=40)
        ids = [i for i in chain.from_iterable(zip_longest(a, b)) if i is not None]
        return poster_items(conn, ctx, ids)
