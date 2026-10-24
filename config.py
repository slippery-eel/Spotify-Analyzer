"""Settings and the vibe playlist definitions.

Each playlist's `name` is matched against your Spotify playlist names (case-insensitive,
whitespace/apostrophe-tolerant, see sync.match_playlists). `description` is your own wording
and goes to the classifier verbatim. `rule`, when set, is a hard constraint.
"""
import os
from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, '.env'))

SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', '')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8080/callback')
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

SPOTIFY_SCOPES = ('user-library-read playlist-read-private playlist-read-collaborative '
                  'playlist-modify-private playlist-modify-public')

# SPOTIFY_DB overrides the DB path (e.g. a demo copy for UI testing)
DB_FILE = os.getenv('SPOTIFY_DB') or os.path.join(_HERE, 'spotify_data.db')
TOKEN_FILE = os.path.join(_HERE, 'token.json')

VIBE_PLAYLISTS = [
    {'key': 'summer', 'name': 'summer time vibes 🏖',
     'description': 'Mostly any fun song, things I could play around others on a beach. But also '
                    'anything that personally reminds me of summer: a warm, sunny feel. Includes some '
                    'songs that are not necessarily fun party songs.'},
    {'key': 'cozy', 'name': 'mega cozy playlist',
     'description': 'Anything cozy and calm and nice.'},
    {'key': 'boots_n_cats', 'name': 'boots n cats',
     'description': 'BOPs. Anything that makes you want to dance without being a rager or dance-club '
                    'song. Chiller than that but still groovy, funky and fun. Most have a really strong '
                    'beat and rhythm. Most of these probably also fit summer time vibes.'},
    {'key': 'spooky', 'name': 'Spooky 👻',
     'description': 'Spooky Halloween-esque vibes, but not legitimately scary or intense like '
                    'soundtracks. Something you could put on for a Halloween party.'},
    {'key': 'damn_im_good', 'name': "d a m n   i ' m   g o o d",
     'description': 'No specific vibe: songs with a really cool and interesting sound. Stuff I could '
                    'show anyone and they would say "oh this is awesome". Prioritize cool sounds and '
                    'rhythms and just COOL songs.'},
    {'key': 'gym', 'name': 'GYM BANGERS',
     'description': 'The most fast-paced bangers and hardest songs for the gym.'},
    {'key': 'villain_1700s', 'name': '1700s Villain Vibe 🧐☠️🔥',
     'description': 'Any classical music with an ominous or mischievous feeling.'},
    {'key': 'thoughtful', 'name': 'thoughtful',
     'description': 'Beautiful, contemplative, even emotional orchestral music. Soundtracks for the '
                    'most part, no words. Songs that make you think and reflect.'},
    {'key': 'detective', 'name': 'Ima detective on the cusp of a major breakthrough',
     'description': 'Detective music: strong consistent beats, forward momentum. Many feel noir and '
                    'detective-y, like an investigation is happening.'},
    {'key': 'suns_comin_up', 'name': "Sun's comin up",
     'description': 'Hopeful, optimistic. Not necessarily happy; some are bittersweet, but something '
                    'about them feels optimistic.'},
    {'key': 'log_cabins', 'name': 'Log cabins 🤠🌲🏕🌲',
     'description': 'Any acoustic and folk music.',
     'rule': 'Only acoustic or folk music. Never suggest electronic, heavily produced, or non-acoustic songs.'},
    {'key': 'alien_christmas', 'name': 'alien christmas',
     'description': 'Songs that for whatever reason feel vaguely Christmas-y. Cozy and happy, maybe '
                    'even winter vibes.'},
    {'key': 'zoinks', 'name': 'Zoinks Scoob are you sure that was just weed?',
     'description': 'TRIPPY songs. Crazy and big sounds, even experimental or new electronic sounds.'},
    {'key': 'moody', 'name': 'moody',
     'description': 'Depressed songs, but not super sad or super emotional; most are fairly '
                    '"unemotional". Slightly dark and heavy, moody music.'},
    {'key': 'afterparty', 'name': 'afterparty',
     'description': 'Sad and emotional songs that still have amazing rhythm and beats and make you '
                    'want to dance.'},
    {'key': 'anti_brain_rot', 'name': 'anti brain rot',
     'description': 'Quiet, nice and simple piano and instrumental music.'},
    {'key': 'mood_fire', 'name': '🔥m🔥o👿o🔥d🔥',
     'description': 'Like Spooky, but ACTUALLY scary and intense. A lot of soundtracks.'},
    {'key': 'oo_la_la', 'name': 'Oo la la  🥰💜',
     'description': 'Nice cute love songs, plus sexy songs.'},
    {'key': 'one_of_those_nights', 'name': 'one of those nights',
     'description': 'Any sad and heavy song that makes you feel yourself.'},
    {'key': 'sad_love_songs', 'name': 'sad love songs',
     'description': 'A subset of "one of those nights": songs about love and relationships with a '
                    'sad/emotional, maybe even angry vibe.'},
]
