import discord
import json
import asyncio
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import string
import numpy as np
import logging

# Load configuration
with open('config.json') as f:
    config = json.load(f)

TOKEN = config['token']
MIN_ACCOUNT_AGE = config['min_account_age']
BLOCK_DEFAULT_PROFILE_PICS = config['block_default_profile_pics']
CAPTCHA_RETRY_LIMIT = config['captcha_retry_limit']
SERVICE_NAME = config['service_name']
WHITELIST = config['whitelist']
CAPTCHA_COLORS = config['captcha_colors']

logging.basicConfig(level=logging.INFO)

def generate_random_text(length=6):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def create_captcha_image(text, width=200, height=70, font_size=36):
    background_color = tuple(int(CAPTCHA_COLORS['background'][i:i+2], 16) for i in (1, 3, 5, 7))
    text_color = tuple(int(CAPTCHA_COLORS['text'][i:i+2], 16) for i in (1, 3, 5, 7))
    noise_color = tuple(int(CAPTCHA_COLORS['noise'][i:i+2], 16) for i in (1, 3, 5, 7))
    line_color = tuple(int(CAPTCHA_COLORS['line'][i:i+2], 16) for i in (1, 3, 5, 7))
    
    image = Image.new('RGBA', (width, height), background_color)
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    text_x = (width - text_width) / 2
    text_y = (height - text_height) / 2
    draw.text((text_x, text_y), text, font=font, fill=text_color)
    
    np_image = np.array(image)
    
    def warp_image(np_img):
        rows, cols, _ = np_img.shape
        dx = (np.random.rand(rows, cols) - 0.5) * 5
        dy = (np.random.rand(rows, cols) - 0.5) * 5
        
        x, y = np.meshgrid(np.arange(cols), np.arange(rows))
        x_new = np.clip(x + dx, 0, cols - 1).astype(int)
        y_new = np.clip(y + dy, 0, rows - 1).astype(int)
        
        warped_img = np_img[y_new, x_new]
        return warped_img
    
    np_image = warp_image(np_image)
    image = Image.fromarray(np_image, 'RGBA')
    
    draw = ImageDraw.Draw(image)
    for _ in range(100):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=noise_color)
    
    for _ in range(5):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line(((x1, y1), (x2, y2)), fill=line_color, width=1)
    
    image = image.filter(ImageFilter.GaussianBlur(1))
    
    return image

def save_captcha_image(image, filename):
    image.save(filename, format='PNG')

class CaptchaBot(discord.Client):
    async def on_ready(self):
        logging.info(f'Logged in as {self.user}')

    async def on_message(self, message):
        if isinstance(message.channel, discord.DMChannel):
            await self.handle_dm(message)
        elif message.author.id in WHITELIST and message.content.startswith('!config'):
            await self.handle_config(message)

    async def handle_dm(self, message):
        await message.author.dm_channel.edit(muted=True)
        
        account_age_days = (discord.utils.utcnow() - message.author.created_at).days
        if account_age_days < MIN_ACCOUNT_AGE:
            await message.author.block()
            return
        
        if BLOCK_DEFAULT_PROFILE_PICS and message.author.default_avatar:
            await message.author.block()
            return
        
        for attempt in range(CAPTCHA_RETRY_LIMIT):
            captcha_text = generate_random_text()
            captcha_image = create_captcha_image(captcha_text)
            captcha_filename = f'/tmp/captcha_{message.author.id}.png'
            save_captcha_image(captcha_image, captcha_filename)
            
            await message.author.send(
                "Welcome to Disflare! To verify that you're a human, please solve the CAPTCHA below. "
                "Enter the text you see in the image."
            )
            await message.author.send(file=discord.File(captcha_filename))
            
            def check(m):
                return m.author == message.author and isinstance(m.channel, discord.DMChannel)
            
            try:
                response = await self.wait_for('message', check=check, timeout=60)
                if response.content.lower() == captcha_text.lower():
                    await message.author.dm_channel.edit(muted=False)
                    await response.add_reaction('✅')
                    break
                else:
                    await response.add_reaction('❌')
            except asyncio.TimeoutError:
                pass
        else:
            await message.author.block()

    async def handle_config(self, message):
        parts = message.content.split(maxsplit=2)
        if len(parts) < 3:
            await message.channel.send("Usage: `!config <key> <value>`")
            return
        
        key, value = parts[1], parts[2]
        
        if key in config:
            try:
                if isinstance(config[key], bool):
                    config[key] = value.lower() in ('true', '1', 'yes')
                elif isinstance(config[key], int):
                    config[key] = int(value)
                else:
                    config[key] = value

                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)
                
                await message.channel.send(f"Updated `{key}` to `{value}`.")
            except ValueError:
                await message.channel.send(f"Invalid value for `{key}`.")
        else:
            await message.channel.send(f"Key `{key}` not found in config.")

intents = discord.Intents.default()
intents.messages = True
intents.members = True
client = CaptchaBot(intents=intents)
client.run(TOKEN)