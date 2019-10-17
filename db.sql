CREATE TABLE `bulletin` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `gid` bigint(20) NOT NULL,
  `content` text NOT NULL,
  `expires` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `bulletin_gid_index` (`gid`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4;