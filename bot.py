import asyncio
import logging
import os

import discord
import requests

from discord.ext import tasks

discord_token = os.getenv('DISCORD_TOKEN')
space_endpoint = os.getenv('SPACE_ENDPOINT')
channel_id = os.getenv('DISCORD_CHANNEL_ID')

avatars = {}
usernames = {
    'closed': 'Closed',
    'open': 'Open'
}

online_status = {
    'closed': discord.Status.offline,
    'open': discord.Status.online
}

people_indicator = '🧙'
channel_name = 'space-is'

current_state = None
current_persons = None

# Logging configuration
logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
client = discord.Client(intents=intents)


async def retry_with_backoff(func, max_attempts=5):
    attempt = 0
    while attempt < max_attempts:
        try:
            return await func()
        except Exception as e:
            attempt += 1
            if attempt == max_attempts:
                raise
            delay = (2 ** attempt) + asyncio.get_event_loop().time() % 1
            logging.warning(f"Attempt {attempt} failed. Retrying in {delay:.2f} seconds...")
            await asyncio.sleep(delay)


async def update_state(state, persons):
    try:
        if not client.user:
            raise ValueError("Client user not found")

        logging.info(f'Updating the presence to "{state}, {persons}"')
        nick = f"{usernames[state]} ({persons} {people_indicator})" if state == 'open' and persons is not None \
            else usernames[state]

        for guild in client.guilds:
            try:
                member = guild.get_member_named(client.user.name)
                await member.edit(nick=nick)
            except Exception as e:
                logging.error(f"Failed to update nickname in guild {guild.name}: {e}")

            # Getting channel ID and setting status for it
            channel = guild.get_channel(int(channel_id))
            if channel:
                lock_icon = "🔴🔒" if state == "closed" else "🟢🔓"
                channel_state = 'closed'  # Set default to closed

                if state != 'closed':
                    channel_state = f"open-{persons or '?'}"

                formatted_channel_name = f"{lock_icon}-{channel_name}-{channel_state}"

                # Setting actual status
                await channel.edit(name=formatted_channel_name)
            else:
                logging.warning(f"Channel {channel_id} not found")

    except Exception as e:
        logging.error(f"Error updating state: {e}")


async def update_presence(state, persons):
    global current_state, current_persons

    if state != current_state or persons != current_persons:
        await update_state(state, persons)
        current_state = state
        current_persons = persons


@tasks.loop(minutes=1)
async def is_there_life_on_mars():
    async def check_status():
        try:
            spaceapi_json = requests.get(space_endpoint, timeout=10).json()
            return spaceapi_json
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logging.error(f"API request failed or timed out: {e}")
            raise

    try:
        logging.info('Checking the status')
        try:
            result = await asyncio.wait_for(retry_with_backoff(check_status), timeout=15)
        except asyncio.TimeoutError:
            logging.error("API operation timed out")

        space_state = 'open' if result['state']['open'] else 'closed'
        people = result['sensors']['people_now_present'][0]['value']
        logging.info(f'Current status: {space_state} ({people} in da haus)')
        await update_presence(space_state, people)
    except requests.exceptions.RequestException as e:
        logging.error(f"Error checking space API after multiple retries: {e}")
    except KeyError as e:
        logging.error(f"Invalid API response: {e}")
    except Exception as e:
        logging.error(f"Unexpected error checking space API: {e}")


@client.event
async def on_ready():
    try:
        logging.info(f'{client.user} has connected to Discord server')
        for state in ['closed', 'open']:
            with open(f'res/glider_{state}.png', 'rb') as avatar:
                avatars[state] = avatar.read()

        await client.user.edit(username='glider')
        await client.user.edit(avatar=avatars['open'])
        await client.change_presence(activity=discord.Activity(name="the Space", type=discord.ActivityType.watching))
    except Exception as e:
        logging.critical(f"Failed to set up bot presence: {e}")
        raise

    is_there_life_on_mars.start()


client.run(discord_token)
