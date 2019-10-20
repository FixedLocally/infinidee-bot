CREATE TABLE `auto_response` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `gid` bigint(20) NOT NULL,
  `msg_type` varchar(10) NOT NULL,
  `msg_text` text NOT NULL,
  `trigger` varchar(64) NOT NULL,
  `entities` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `bulletin` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `gid` bigint(20) NOT NULL,
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `expires` int(11) NOT NULL,
  `msg_id` int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`msg_id`,`id`),
  UNIQUE KEY `BULLETIN_id_uindex` (`id`),
  KEY `bulletin_gid_index` (`gid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `group_settings` (
  `gid` bigint(20) NOT NULL,
  `welcome` text,
  `flood_threshold` int(11) DEFAULT NULL,
  `flood_action` varchar(5) DEFAULT 'mute',
  PRIMARY KEY (`gid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `schedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `start_time` int(11) NOT NULL,
  `end_time` int(11) NOT NULL,
  `event` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci