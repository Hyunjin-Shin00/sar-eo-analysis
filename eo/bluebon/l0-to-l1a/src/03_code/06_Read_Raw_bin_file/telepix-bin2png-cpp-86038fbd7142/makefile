# Compiler settings
CXX = $(CROSS_COMPILE)g++
CXXFLAGS = -Wall
LDFLAGS = -L. -lssl -lcrypto -lpng -lz -ltiff -std=c++17

# Include Directories
INCLUDE_DIR = ./
CXXFLAGS += -I$(INCLUDE_DIR)

# Source files
SOURCES = main.cpp 

# Object files directory
OBJDIR = obj

# Object files
OBJECTS = $(patsubst %.cpp,$(OBJDIR)/%.o,$(SOURCES))

# Executable name
EXECUTABLE = main

# Check if the DEBUG flag is set
ifeq ($(DEBUG),1)
    CXXFLAGS += -DDEBUG_OUTPUT
endif

# Default target
all: $(EXECUTABLE)

# Linking the executable
$(EXECUTABLE): $(OBJECTS)
	$(CXX) $(OBJECTS) -o $@ $(LDFLAGS)

# Compiling source files
$(OBJDIR)/%.o: %.cpp
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

# Clean up
clean:
	rm -f $(OBJECTS) $(EXECUTABLE)

# Phony targets
.PHONY: all clean
