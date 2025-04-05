import React, { useState, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';

const App = () => {
  const [selectedPoint, setSelectedPoint] = useState(3); // Default at middle point
  const translateX = useRef(new Animated.Value(0)).current; // For smooth movement
  const points = [1, 2, 3, 4, 5]; // Defined points
  const totalWidth = 300; // Width of the slider
  const pointSpacing = totalWidth / (points.length - 1); // Distance between points

  const handleMove = (event) => {
    let touchX = event.nativeEvent.locationX; // Get touch position
    if (touchX < 0) touchX = 0;
    if (touchX > totalWidth) touchX = totalWidth;
    
    Animated.timing(translateX, {
      toValue: touchX,
      duration: 0,
      useNativeDriver: false,
    }).start();
  };

  const handleRelease = () => {
    let currentX = translateX._value;
    let closestPointIndex = Math.round(currentX / pointSpacing);
    let snappedX = closestPointIndex * pointSpacing;
    setSelectedPoint(points[closestPointIndex]);

    Animated.timing(translateX, {
      toValue: snappedX,
      duration: 200,
      useNativeDriver: false,
    }).start();
  };

  return (
    <View style={styles.container}>
      <View style={styles.slider} onStartShouldSetResponder={() => true} 
        onResponderMove={handleMove} onResponderRelease={handleRelease}>
        
        {points.map((point, index) => (
          <View key={point} style={[styles.point, { left: index * pointSpacing }]} />
        ))}

        <Animated.View style={[styles.handle, { transform: [{ translateX }] }]} />
      </View>

      <Text style={styles.text}>Selected Point: {selectedPoint}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#f5f5f5' },
  slider: { width: 300, height: 50, justifyContent: 'center', position: 'relative', backgroundColor: '#ddd', borderRadius: 10 },
  point: { width: 10, height: 10, borderRadius: 5, backgroundColor: 'black', position: 'absolute', top: 20 },
  handle: { width: 20, height: 20, borderRadius: 10, backgroundColor: 'blue', position: 'absolute', top: 15 },
  text: { marginTop: 20, fontSize: 18, fontWeight: 'bold' }
});

export default App;
