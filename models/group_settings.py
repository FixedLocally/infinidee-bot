class GroupSettings:
    welcome = ''
    flood_threshold = 5
    flood_action = 'mute'

    def __init__(self, row):
        self.welcome = row[0]
        self.flood_threshold = row[1]
        self.flood_action = row[2]


__all__ = ['GroupSettings']
