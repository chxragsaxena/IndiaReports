package hub

import "math"

// TileSize is the edge of a fan-out tile in degrees (~111 km). A report is only
// offered to clients registered on its tile, never to every connected client.
const TileSize = 1.0

// Bounding box of India. Viewports are clamped to it so a client cannot register
// thousands of tiles.
const (
	indiaMinLat = 6.0
	indiaMaxLat = 38.0
	indiaMinLng = 68.0
	indiaMaxLng = 98.0
)

type Tile struct{ Lat, Lng int32 }

type BBox struct{ MinLat, MinLng, MaxLat, MaxLng float64 }

func (b BBox) Contains(lat, lng float64) bool {
	return lat >= b.MinLat && lat <= b.MaxLat && lng >= b.MinLng && lng <= b.MaxLng
}

func (b BBox) Valid() bool {
	for _, v := range []float64{b.MinLat, b.MinLng, b.MaxLat, b.MaxLng} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return b.MinLat < b.MaxLat && b.MinLng < b.MaxLng
}

func TileOf(lat, lng float64) Tile {
	return Tile{
		Lat: int32(math.Floor(lat / TileSize)),
		Lng: int32(math.Floor(lng / TileSize)),
	}
}

// TilesFor returns every tile the box overlaps, clamped to India.
func TilesFor(b BBox) []Tile {
	minLat := math.Max(b.MinLat, indiaMinLat)
	maxLat := math.Min(b.MaxLat, indiaMaxLat)
	minLng := math.Max(b.MinLng, indiaMinLng)
	maxLng := math.Min(b.MaxLng, indiaMaxLng)
	if minLat > maxLat || minLng > maxLng {
		return nil
	}
	lo, hi := TileOf(minLat, minLng), TileOf(maxLat, maxLng)
	tiles := make([]Tile, 0, int(hi.Lat-lo.Lat+1)*int(hi.Lng-lo.Lng+1))
	for la := lo.Lat; la <= hi.Lat; la++ {
		for ln := lo.Lng; ln <= hi.Lng; ln++ {
			tiles = append(tiles, Tile{la, ln})
		}
	}
	return tiles
}
