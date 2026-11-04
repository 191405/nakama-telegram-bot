"""Daily Anime Trivia & Bounty Quiz generator."""

from __future__ import annotations

import hashlib
import random

TRIVIA_BANK: list[dict] = [
    {
        "question": "In One Piece, what is the name of Zoro's cursed sword that he received in Loguetown?",
        "options": ["Wado Ichimonji", "Sandai Kitetsu", "Shusui", "Enma"],
        "correct": 1,
        "explanation": "Zoro tested his luck against the curse of Sandai Kitetsu at the sword shop in Loguetown!",
    },
    {
        "question": "In Jujutsu Kaisen, what is Satoru Gojo's Innate Technique passed down in the Gojo Clan?",
        "options": ["Ten Shadows", "Limitless", "Blood Manipulation", "Idle Transfiguration"],
        "correct": 1,
        "explanation": "Limitless (Mugen) allows Gojo to manipulate space at an atomic level, including Infinity, Blue, Red, and Purple.",
    },
    {
        "question": "In Demon Slayer, what color does Tanjiro Kamado's Nichirin blade turn?",
        "options": ["Crimson Red", "Pitch Black", "Deep Blue", "Pure White"],
        "correct": 1,
        "explanation": "A pitch-black Nichirin blade is rare and is associated with users of Sun Breathing!",
    },
    {
        "question": "In Hunter x Hunter, what type of Nen does Killua Zoldyck have?",
        "options": ["Enhancer", "Transmuter", "Conjurer", "Specialist"],
        "correct": 1,
        "explanation": "Killua is a Transmuter, allowing him to change the properties of his aura into electricity.",
    },
    {
        "question": "In Attack on Titan, who was the first person to breach Wall Maria in Episode 1?",
        "options": ["Armored Titan", "Colossal Titan", "Beast Titan", "Female Titan"],
        "correct": 1,
        "explanation": "Bertholdt's 60-meter Colossal Titan kicked open the outer gate of Shiganshina District.",
    },
    {
        "question": "In Naruto, what was the primary forbidden jutsu Naruto learned from the sacred scroll in Chapter 1?",
        "options": ["Rasengan", "Multi Shadow Clone Jutsu", "Flying Raijin", "Reanimation"],
        "correct": 1,
        "explanation": "Naruto mastered the Multi Shadow Clone Jutsu (Taju Kage Bunshin no Jutsu) overnight after stealing the scroll.",
    },
    {
        "question": "In Bleach, what is the release command for Ichigo's Zanpakuto, Zangetsu?",
        "options": ["Roar", "Scatter", "It has no release command (Constant Release)", "Pierce"],
        "correct": 2,
        "explanation": "Zangetsu was initially known as a constant-release type Zanpakuto and had no standard release command.",
    },
    {
        "question": "In Chainsaw Man, which devil does Denji fuse with to become Chainsaw Man?",
        "options": ["Pochita (Chainsaw Devil)", "Fox Devil", "Curse Devil", "Blood Devil"],
        "correct": 0,
        "explanation": "Pochita gave his heart to Denji through a contract to save his life.",
    },
    {
        "question": "In Death Note, what is the favorite snack of the Shinigami Ryuk?",
        "options": ["Chocolate", "Apples", "Potato Chips", "Lollipops"],
        "correct": 1,
        "explanation": "Ryuk is notoriously addicted to juicy red Earth apples!",
    },
    {
        "question": "In Fullmetal Alchemist: Brotherhood, what is the fundamental law of Alchemy?",
        "options": ["Philosopher's Rule", "Equivalent Exchange", "Transmutation Mandate", "Truth Law"],
        "correct": 1,
        "explanation": "'Humankind cannot gain anything without first giving something in return. To obtain, something of equal value must be lost.'",
    },
]


def get_random_trivia() -> dict:
    """Return a randomly chosen anime trivia question with a unique hash."""
    q = random.choice(TRIVIA_BANK)
    q_hash = hashlib.sha256(q["question"].encode()).hexdigest()[:16]
    return {
        "hash": q_hash,
        "question": q["question"],
        "options": q["options"],
        "correct": q["correct"],
        "explanation": q["explanation"],
    }
